param([ValidatePattern('^[a-z0-9-]+$')][string]$Name = 'touch-rate-r48',
      [ValidateRange(20,900)][int]$Seconds = 120,
      [ValidateRange(500,10000)][int]$Frames = 1500)
# Read only physical touchscreen evdev events; keep the collector ready across user reply timing.
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$adb = Join-Path $workspace 'tools/platform-tools/adb.exe'
$evidence = Join-Path $workspace 'reports/device/20261111-simple'
New-Item -ItemType Directory -Force $evidence | Out-Null
$path = Join-Path $evidence ($Name + '.events')
if (Test-Path -LiteralPath $path) { throw 'Capture exists; use a new name.' }
if ((& $adb -s ca10ede3 shell getprop ro.boot.slot_suffix).Trim() -ne '_a' -or
    (& $adb -s ca10ede3 shell getprop ro.build.fingerprint).Trim() -ne
    'Xiaomi/lineage_sheng/sheng:17/CP2A.260605.016/eng.root:userdebug/test-keys') { throw 'Wrong target.' }
$devices = (& $adb -s ca10ede3 shell 'cat /proc/bus/input/devices' | Out-String)
$touch = $devices -split '(?:\r?\n){2,}' | Where-Object { $_ -match 'Name="NVTCapacitiveTouchScreen"' }
if (@($touch).Count -ne 1 -or $touch -notmatch 'Handlers=.*\b(event\d+)\b') { throw 'Touch device missing.' }
$node = '/dev/input/' + $Matches[1]
$start = [Diagnostics.ProcessStartInfo]::new()
$start.FileName = $adb
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
foreach ($arg in @('-s','ca10ede3','shell','getevent','-lt',$node)) { $start.ArgumentList.Add($arg) }
$process = [Diagnostics.Process]::new()
$process.StartInfo = $start
$writer = [IO.StreamWriter]::new($path, $false, [Text.UTF8Encoding]::new($false))
$writer.AutoFlush = $true
$count = 0
$started = $false
try {
    if (-not $process.Start()) { throw 'Collector could not start.' }
    $started = $true
    $errors = $process.StandardError.ReadToEndAsync()
    $line = $process.StandardOutput.ReadLineAsync()
    Write-Output "READY target=ca10ede3 node=$node duration=$Seconds frames=$Frames"
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $nextProgress = 10
    while ($timer.Elapsed.TotalSeconds -lt $Seconds -and $count -lt $Frames) {
        if ($line.Wait(250)) {
            if ($null -eq $line.Result) { break }
            $writer.WriteLine($line.Result)
            if ($line.Result -match '\bSYN_REPORT\b') { $count++ }
            $line = $process.StandardOutput.ReadLineAsync()
        }
        if ($timer.Elapsed.TotalSeconds -ge $nextProgress) {
            Write-Output "CAPTURING elapsed=$([int]$timer.Elapsed.TotalSeconds) reports=$count"
            $nextProgress += 10
        }
    }
    if (-not $process.HasExited) { $process.Kill(); $process.WaitForExit() }
    $stderr = $errors.GetAwaiter().GetResult()
    if ($stderr.Trim()) { Write-Output $stderr.Trim() }
    Write-Output "FINISHED reports=$count file=$path"
    if ($count -lt 500) { throw 'Insufficient physical reports; this capture cannot establish a rate change.' }
} finally {
    if ($started -and -not $process.HasExited) { $process.Kill(); $process.WaitForExit() }
    $writer.Dispose()
    $process.Dispose()
}
