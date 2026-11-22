param([ValidatePattern('^[a-z0-9-]+$')][string]$Name = 'touch-rate-r50-system',
      [ValidateRange(30,900)][int]$Seconds = 600)
# Exercise the installed standard setting/HAL path, never a direct THP setter.
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$adb = Join-Path $workspace 'tools/platform-tools/adb.exe'
$evidence = Join-Path $workspace 'reports/device/20261111-simple'
$events = Join-Path $evidence ($Name + '.events')
$receipt = Join-Path $evidence ($Name + '.phases.json')
if ((Test-Path $events) -or (Test-Path $receipt)) { throw 'Use a fresh capture name.' }
function Adb([string]$command) {
    $value = (& $adb -s ca10ede3 shell $command 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw $value }
    return $value
}
function Uptime {
    return [double]::Parse((Adb 'cat /proc/uptime').Split(' ')[0], [Globalization.CultureInfo]::InvariantCulture)
}
function Set-Report([int]$desired) {
    $before = Uptime
    $answer = Adb "content call --uri content://lineagesettings/system --method PUT_system --arg high_touch_polling_rate_enable --extra value:s:$desired --extra _user:i:0"
    Start-Sleep -Milliseconds 1200
    if ((Adb 'getprop persist.vendor.sheng.touch.report_high') -ne "$desired") {
        throw 'Standard setting did not propagate to the typed HAL property.'
    }
    return @{ desired=$desired; before=$before; after=(Uptime); answer=$answer }
}
if ((Adb 'getprop ro.boot.slot_suffix') -ne '_a' -or
    (Adb 'getprop ro.build.fingerprint') -ne 'Xiaomi/lineage_sheng/sheng:17/CP2A.260605.016/eng.root:userdebug/test-keys' -or
    (Adb 'getenforce') -ne 'Enforcing' -or
    (Adb 'getprop init.svc.vendor.touch-hal') -ne 'running') { throw 'Wrong target/runtime.' }
$devices = Adb 'cat /proc/bus/input/devices'
$touch = $devices -split '(?:\r?\n){2,}' | Where-Object { $_ -match 'Name="NVTCapacitiveTouchScreen"' }
if (@($touch).Count -ne 1 -or $touch -notmatch 'Handlers=.*\b(event\d+)\b') { throw 'Missing physical touchscreen.' }
$node = '/dev/input/' + $Matches[1]
$original = Adb 'getprop persist.vendor.sheng.touch.report_high'
if ($original -notin @('0','1')) { $original = '0' }
$bootId = Adb 'cat /proc/sys/kernel/random/boot_id'
$start = [Diagnostics.ProcessStartInfo]::new()
$start.FileName = $adb
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
foreach ($arg in @('-s','ca10ede3','shell','getevent','-lt',$node)) { $start.ArgumentList.Add($arg) }
$process = [Diagnostics.Process]::new()
$process.StartInfo = $start
$writer = [IO.StreamWriter]::new($events, $false, [Text.UTF8Encoding]::new($false))
$writer.AutoFlush = $true
$transitions = [Collections.Generic.List[object]]::new()
$slots = @{}
$slot = 0
$phase = 0
$count = 0
$dropped = 0
$started = $false
$complete = $false
try {
    $initial = Set-Report 0
    $settled = $initial.after + 0.1
    if (-not $process.Start()) { throw 'Collector failed to start.' }
    $started = $true
    $errors = $process.StandardError.ReadToEndAsync()
    $line = $process.StandardOutput.ReadLineAsync()
    Write-Output "READY standard-setting baseline/high/low/high target=ca10ede3 node=$node"
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $nextProgress = 10
    while ($timer.Elapsed.TotalSeconds -lt $Seconds) {
        if ($line.Wait(250)) {
            if ($null -eq $line.Result) { throw 'Collector ended early.' }
            $value = $line.Result
            $writer.WriteLine($value)
            if ($value -match 'ABS_MT_SLOT\s+([0-9a-f]+)') { $slot = [Convert]::ToInt32($Matches[1],16) }
            if ($value -match 'ABS_MT_TRACKING_ID\s+([0-9a-f]+)') {
                if ($Matches[1] -eq 'ffffffff') { $slots.Remove($slot) } else { $slots[$slot] = $Matches[1] }
            }
            if ($value -match '\bSYN_DROPPED\b') { $dropped++; throw 'Dropped input events.' }
            if ($value -match '^\[\s*(\d+\.\d+)\].*\bSYN_REPORT\b' -and $slots.Count -eq 1) {
                $stamp = [double]::Parse($Matches[1], [Globalization.CultureInfo]::InvariantCulture)
                if ($stamp -gt $settled) { $count++ }
            }
            $line = $process.StandardOutput.ReadLineAsync()
            if ($count -ge 850) {
                if ($phase -eq 3) { $complete = $true; break }
                if ((Adb 'cat /sys/class/drm/card0-DSI-1/dpms') -ne 'On') { throw 'Screen went Off during comparison.' }
                $desired = if ($phase -eq 1) { 0 } else { 1 }
                $transition = Set-Report $desired
                $transitions.Add($transition)
                $settled = $transition.after + 0.1
                $phase++; $count = 0
                Write-Output "TRANSITION phase=$phase desired=$desired"
            }
        }
        if ($timer.Elapsed.TotalSeconds -ge $nextProgress) {
            Write-Output "CAPTURING phase=$phase active_reports=$count elapsed=$([int]$timer.Elapsed.TotalSeconds)"
            $nextProgress += 10
        }
    }
    if (-not $complete) { throw 'Physical frame goal not reached.' }
    if ((Adb 'cat /proc/sys/kernel/random/boot_id') -ne $bootId -or (Adb 'getenforce') -ne 'Enforcing') { throw 'Runtime changed.' }
    @{ passed=$true; setting='high_touch_polling_rate_enable'; initial=$initial; commands=@($transitions);
       bootId=$bootId; syn_dropped=$dropped; final_requested=1; direct_thp_setter_used=$false } |
        ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 $receipt
    Write-Output "FINISHED four physical windows; standard setting left ON; $receipt"
} finally {
    if ($started -and -not $process.HasExited) { $process.Kill(); $process.WaitForExit() }
    $writer.Dispose()
    $process.Dispose()
    if (-not $complete) { $null = Set-Report ([int]$original) }
}
