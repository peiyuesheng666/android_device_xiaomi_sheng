# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param(
    [string]$Serial,
    [ValidateRange(15,1800)][int]$Seconds = 180,
    [switch]$UseSu,
    [switch]$Bugreport,
    [switch]$NoPause,
    [string]$OutputRoot
)
$ErrorActionPreference = 'Stop'
if (!$OutputRoot) { $OutputRoot = Join-Path $PSScriptRoot 'logs' }
$adb = Join-Path $PSScriptRoot 'platform-tools\adb.exe'
if (!(Test-Path -LiteralPath $adb)) {
    $found = Get-Command adb.exe -ErrorAction SilentlyContinue
    if (!$found) { throw 'ADB missing. Extract the entire kit first, or put platform-tools beside this script.' }
    $adb = $found.Source
}
# Windows argv quoting, including embedded quotes and trailing backslashes.
function Quote-Arg([string]$Value) {
    '"' + ([regex]::Replace([regex]::Replace($Value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1')) + '"'
}
function Invoke-Adb([string[]]$Arguments, [int]$Timeout = 20) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $adb
    $psi.Arguments = (($Arguments | ForEach-Object { Quote-Arg $_ }) -join ' ')
    $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
    $p = New-Object System.Diagnostics.Process; $p.StartInfo = $psi
    [void]$p.Start()
    $outTask = $p.StandardOutput.ReadToEndAsync(); $errTask = $p.StandardError.ReadToEndAsync()
    $timedOut = !$p.WaitForExit($Timeout * 1000)
    if ($timedOut) { $p.Kill(); $p.WaitForExit() }
    $result = [pscustomobject]@{ ExitCode=$p.ExitCode; Timeout=$timedOut; Stdout=$outTask.Result; Stderr=$errTask.Result }
    $p.Dispose(); return $result
}
$devices = Invoke-Adb @('devices','-l')
Write-Host $devices.Stdout
if (!$Serial) {
    $ready = @($devices.Stdout -split '\r?\n' | Where-Object { $_ -match '^\S+\s+device(?:\s|$)' } | ForEach-Object { ($_ -split '\s+')[0] })
    if ($ready.Count -eq 1) { $Serial = $ready[0] }
    elseif ($ready.Count -gt 1) { $Serial = Read-Host 'Multiple devices: enter the tablet serial/address from the list' }
    else { throw 'No authorized device. Enable USB/wireless debugging, authorize this PC, then retry.' }
}
$initial = Invoke-Adb @('-s',$Serial,'shell','getprop ro.serialno; getprop ro.product.device; getprop ro.build.fingerprint; id')
if ($initial.ExitCode -ne 0 -or $initial.Timeout -or !$initial.Stdout.Trim()) { throw "Device unavailable: $($initial.Stderr)" }
$identityLines = $initial.Stdout.Trim() -split '\r?\n'
$hardwareSerial = $identityLines[0].Trim()
if ($hardwareSerial -notmatch '^[A-Za-z0-9._-]+$') { throw 'Cannot verify device serial safely.' }
Write-Host "Target: $Serial`n$($initial.Stdout)"
if (!$NoPause) { [void](Read-Host 'Confirm this is the tablet. Press Enter to start recording') }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$dir = Join-Path $OutputRoot "usb-$stamp"
[void](New-Item -ItemType Directory -Path $dir -Force)
$records = New-Object System.Collections.Generic.List[object]
$events = New-Object System.Collections.Generic.List[object]
$streams = @{}; $streamNumber = 0; $reportedEnded = @{}
$remote = "/data/local/tmp/sheng-usb-capture-$stamp.sh"
$effectiveUseSu = $false
$initial.Stdout | Set-Content -LiteralPath (Join-Path $dir 'identity.txt') -Encoding UTF8
function Add-Event([string]$Message) {
    $entry = [pscustomobject]@{ time=(Get-Date).ToString('o'); message=$Message }
    $events.Add($entry); Write-Host "[$(Get-Date -Format HH:mm:ss)] $Message"
}
function Shell-Command([string]$Command, [switch]$Privileged) {
    if ($Privileged -and $effectiveUseSu) { return "su -c '" + $Command.Replace("'", "'\''") + "'" }
    return $Command
}
function Save-Shell([string]$Name, [string]$Command, [int]$Timeout=20, [switch]$Privileged) {
    $result = Invoke-Adb @('-s',$Serial,'shell',(Shell-Command $Command -Privileged:$Privileged)) $Timeout
    ($result.Stdout + "`n[stderr]`n" + $result.Stderr) | Set-Content -LiteralPath (Join-Path $dir "$Name.txt") -Encoding UTF8
    $records.Add([pscustomobject]@{ time=(Get-Date).ToString('o'); name=$Name; command=$Command; exitCode=$result.ExitCode; timeout=$result.Timeout })
}
function Save-Snapshot([string]$Name) {
    Save-Shell "$Name-state" "sh $remote" 15 -Privileged
    Save-Shell "$Name-usb" 'dumpsys usb' 15
}
function Start-Stream([string]$Name, [string]$Command) {
    $script:streamNumber++
    $base = Join-Path $dir ("{0}-{1:D3}" -f $Name,$script:streamNumber)
    $argv = @('-s',$Serial,'shell',$Command) | ForEach-Object { Quote-Arg $_ }
    $process = Start-Process -FilePath $adb -ArgumentList ($argv -join ' ') -NoNewWindow -PassThru -RedirectStandardOutput "$base.log" -RedirectStandardError "$base.err.txt"
    $script:streams[$Name] = $process
    $records.Add([pscustomobject]@{ time=(Get-Date).ToString('o'); name=$Name; command=$Command; file=[IO.Path]::GetFileName("$base.log") })
}
function Save-Windows([string]$Name) {
    try {
        Get-CimInstance Win32_PnPEntity -OperationTimeoutSec 10 | Where-Object { $_.PNPDeviceID -match '^(USB|SWD\\WPDBUSENUM)' } |
            Select-Object Name,PNPDeviceID,Service,Status,ConfigManagerErrorCode |
            ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $dir "$Name-windows-usb.json") -Encoding UTF8
    } catch { $_ | Out-String | Set-Content -LiteralPath (Join-Path $dir "$Name-windows-usb-error.txt") }
}
try {
    $push = Invoke-Adb @('-s',$Serial,'push',(Join-Path $PSScriptRoot 'capture-state.sh'),$remote)
    if ($push.ExitCode -ne 0 -or $push.Timeout) { throw "Probe upload failed: $($push.Stderr)" }
    if ($UseSu) {
        $suProbe = Invoke-Adb @('-s',$Serial,'shell',"su -c 'id'") 15
        ($suProbe | ConvertTo-Json) | Set-Content -LiteralPath (Join-Path $dir 'su-probe.json') -Encoding UTF8
        $effectiveUseSu = !$suProbe.Timeout -and $suProbe.ExitCode -eq 0 -and $suProbe.Stdout -match 'uid=0\('
        if (!$effectiveUseSu) { Add-Event 'su unavailable or unauthorized; collecting with existing ADB permissions.' }
    }
    Save-Shell 'kernel-logcat-before' 'logcat -b kernel -d -v threadtime' 20
    Save-Shell 'permissions' 'id; command -v su; ls -ld /sys/kernel/debug; dmesg | head -n 8' 15 -Privileged
    Save-Shell 'properties' 'getprop'
    Save-Shell 'kernel-before' 'dmesg' 20 -Privileged
    Start-Stream 'logcat' 'logcat -b all -v threadtime -T 1'
    Start-Stream 'kernel' (Shell-Command 'dmesg -w' -Privileged)
    Save-Snapshot 'before'
    Save-Shell 'display-before' 'dumpsys display' 20
    Save-Shell 'surfaceflinger-before' 'dumpsys SurfaceFlinger' 20
    Save-Shell 'charging-before' 'dumpsys battery; dumpsys thermalservice' 20
    Save-Windows 'before'
    Add-Event "Recording for $Seconds seconds. Reproduce now: unplug, wait 5 seconds, reconnect; try file transfer or DP."
    Add-Event 'Keep this window open. Wireless ADB is recommended for DP; USB ADB interruptions will be recorded.'
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    $tick = 0; $wasOnline = $true; $identityMismatch = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        $tick++
        # Recheck immutable identity before every batch, including after reconnect.
        $check = Invoke-Adb @('-s',$Serial,'shell','getprop ro.serialno') 4
        $online = !$check.Timeout -and $check.ExitCode -eq 0 -and $check.Stdout.Trim() -eq $hardwareSerial
        if (!$check.Timeout -and $check.ExitCode -eq 0 -and $check.Stdout.Trim() -and $check.Stdout.Trim() -ne $hardwareSerial) {
            $identityMismatch = $true; Add-Event 'Device identity changed; stopping collection.'; break
        }
        if ($online) {
            if (!$wasOnline) { Add-Event 'ADB restored; collection resumed.' }
            foreach ($name in @('logcat','kernel')) {
                if ($streams[$name].HasExited) {
                    if (!$reportedEnded.ContainsKey($streams[$name].Id)) {
                        Add-Event "$name stream ended (exit $($streams[$name].ExitCode)); see its error file."
                        $reportedEnded[$streams[$name].Id] = $true
                    }
                    # Unsupported dmesg -w / permission denial: use periodic snapshots instead.
                    if ($name -eq 'logcat' -or !$wasOnline) {
                        $cmd = if ($name -eq 'logcat') { 'logcat -b all -v threadtime -T 1' } else { Shell-Command 'dmesg -w' -Privileged }
                        $streams[$name].Dispose()
                        Start-Stream $name $cmd
                    }
                }
            }
            Save-Snapshot ('sample-{0:D3}' -f $tick)
            if (($tick % 3) -eq 0) { Save-Shell ('kernel-{0:D3}' -f $tick) 'dmesg' 12 -Privileged }
        } elseif ($wasOnline) { Add-Event 'ADB disconnected/unavailable. This interval has a capture gap.' }
        $wasOnline = $online
        Start-Sleep -Seconds 3
    }
    if (!$identityMismatch) {
        $check = Invoke-Adb @('-s',$Serial,'shell','getprop ro.serialno') 4
        if ($check.Stdout.Trim() -eq $hardwareSerial -and $check.ExitCode -eq 0) {
            Save-Snapshot 'after'
            Save-Shell 'kernel-after' 'dmesg' 20 -Privileged
            Save-Shell 'kernel-logcat-buffer' 'logcat -b kernel -d -v threadtime' 20
            Save-Shell 'display-after' 'dumpsys display' 20
            Save-Shell 'surfaceflinger-after' 'dumpsys SurfaceFlinger' 20
            Save-Shell 'audio-after' 'dumpsys media.audio_policy; dumpsys media.audio_flinger' 25
            Save-Shell 'crashes' 'logcat -b crash -d -v threadtime' 20
            Save-Shell 'services' 'service list; ps -A' 15
            Save-Shell 'charging-after' 'dumpsys battery; dumpsys thermalservice' 20
            if ($Bugreport) {
                Add-Event 'Creating optional Android bugreport (up to 5 minutes).'
                $bug = Invoke-Adb @('-s',$Serial,'bugreport',(Join-Path $dir 'bugreport.zip')) 300
                ($bug | ConvertTo-Json) | Set-Content -LiteralPath (Join-Path $dir 'bugreport-result.json') -Encoding UTF8
            }
            # Only remove this run's temporary probe.
            [void](Invoke-Adb @('-s',$Serial,'shell',"rm -f $remote") 5)
        } else { Add-Event 'Device unavailable at end; final device snapshot skipped.' }
    }
    Save-Windows 'after'
} catch {
    Add-Event "Capture error: $_"
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $dir 'capture-error.txt') -Encoding UTF8
} finally {
    foreach ($p in $streams.Values) {
        if (!$p.HasExited) { $p.Kill(); $p.WaitForExit() }
        $p.Dispose()
    }
    $records.ToArray() | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $dir 'commands.json') -Encoding UTF8
    ConvertTo-Json -InputObject @($events.ToArray()) -Depth 4 | Set-Content -LiteralPath (Join-Path $dir 'events.json') -Encoding UTF8
    [pscustomobject]@{ toolVersion=2; started=$stamp; finished=(Get-Date).ToString('o'); transport=$Serial; hardwareSerial=$hardwareSerial; suRequested=[bool]$UseSu; suActive=[bool]$effectiveUseSu; bugreportRequested=[bool]$Bugreport; requestedSeconds=$Seconds; windows=$env:OS } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dir 'manifest.json') -Encoding UTF8
    @'
Interpretation: gadget current_speed is the negotiated tablet-to-PC link speed.
maximum_speed is capability only. Host devices use /sys/bus/usb/devices/*/speed:
480 = USB 2 high-speed; 5000/10000 = SuperSpeed. USB2 peripherals can coexist on a USB3 hub.
DP rate and lane count must be read from DP/DRM/kernel logs; USB speed alone cannot prove DP health.
Permission denied / unsupported commands / ADB gaps limit the evidence; see commands.json and *.err.txt.
This tool does not change USB modes, reboot, clear logs, enable root, mount debugfs, or flash anything.
Logs may contain device IDs, network names/addresses and application activity. Review before public sharing.
'@ | Set-Content -LiteralPath (Join-Path $dir 'READ-ME.txt') -Encoding UTF8
    $zip = "$dir.zip"
    Compress-Archive -LiteralPath $dir -DestinationPath $zip -CompressionLevel Optimal
    Write-Host "`nSaved: $zip`nSend this ZIP to the maintainer."
}
if (!$NoPause) { [void](Read-Host 'Finished. Press Enter to close') }
