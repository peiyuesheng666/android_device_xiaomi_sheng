param([ValidatePattern('^[a-z0-9-]+$')][string]$Name)
# Observe the separate flushed collector and switch only the verified stock boolean game mode.
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$adb = Join-Path $workspace 'tools/platform-tools/adb.exe'
$evidence = Join-Path $workspace 'reports/device/20261111-simple'
$events = Join-Path $evidence ($Name + '.events')
$result = Join-Path $evidence ($Name + '-phases.json')
if (-not $Name -or -not (Test-Path -LiteralPath $events) -or (Test-Path -LiteralPath $result)) { throw 'Wrong capture path.' }
$commands = [Collections.Generic.List[object]]::new()
$deadline = (Get-Date).AddSeconds(600)
$gameEnabled = $false
function Invoke-Target([string]$command) {
    $output = (& $adb -s ca10ede3 shell $command 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw $output }
    return $output
}
function Count-Reports {
    $stream = [IO.File]::Open($events, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    $reader = [IO.StreamReader]::new($stream)
    try { $text = $reader.ReadToEnd() } finally { $reader.Dispose() }
    return [regex]::Matches($text, '\bSYN_REPORT\b').Count
}
function Wait-Reports([int]$count) {
    while ((Count-Reports) -lt $count) {
        if ((Get-Date) -ge $deadline) { throw 'Physical motion not captured in the bounded trial.' }
        Start-Sleep -Milliseconds 250
    }
}
function Change-Game([int]$value) {
    if ($value -notin @(0,1)) { throw 'Invalid game value.' }
    $output = Invoke-Target "cat /proc/uptime; /data/local/tmp/sheng-touch-sampling-probe $value; cat /proc/uptime"
    $times = [regex]::Matches($output, '(?m)^(\d+\.\d+)\s+\d+\.\d+\s*$')
    if ($times.Count -ne 2 -or $output -notmatch "stock_mode=0 desired=$value ioctl_result=0") { throw $output }
    $record = [pscustomobject]@{ desired=$value; before=[double]$times[0].Groups[1].Value;
        after=[double]$times[1].Groups[1].Value; output=$output }
    $commands.Add($record)
    Write-Output "GAME value=$value before=$($record.before) after=$($record.after)"
}
if ((Invoke-Target 'getprop ro.boot.slot_suffix') -ne '_a' -or
    (Invoke-Target 'getprop ro.build.fingerprint') -ne
    'Xiaomi/lineage_sheng/sheng:17/CP2A.260605.016/eng.root:userdebug/test-keys' -or
    (Invoke-Target 'cat /proc/xm_htc_game_mode') -notmatch 'game_mode:\s*0\b') { throw 'Wrong target or nonbaseline game mode.' }
try {
    Write-Output 'READY comparison waiting for 600 physical baseline reports'
    Wait-Reports 600
    $gameEnabled = $true
    Change-Game 1
    $highStartCount = Count-Reports
    Wait-Reports ($highStartCount + 650)
    Change-Game 0
    $gameEnabled = $false
    $restoredStartCount = Count-Reports
    Wait-Reports ($restoredStartCount + 650)
    @{ passed=$true; commands=@($commands); gameRestored=$true;
       scanState=(Invoke-Target 'cat /sys/class/drm/card0-DSI-1/dpms; cat /proc/xm_htc_hand_scan_rate; cat /proc/xm_htc_game_mode') } |
        ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 $result
    $collectors = Invoke-Target 'ps -A -o PID,ARGS'
    $matches = [regex]::Matches($collectors, '(?m)^\s*(\d+) getevent -lt /dev/input/event6\s*$')
    if ($matches.Count -ne 1) { throw 'Collector is not uniquely identified.' }
    $collectorPid = [int]$matches[0].Groups[1].Value
    Invoke-Target "test `"`$(cat /proc/$collectorPid/comm)`" = getevent && kill -TERM $collectorPid" | Out-Null
    Write-Output "FINISHED comparison and stock game mode restored; phases=$result"
} finally {
    if ($gameEnabled) { Change-Game 0 }
}
