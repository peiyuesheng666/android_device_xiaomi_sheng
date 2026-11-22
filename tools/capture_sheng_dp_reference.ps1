param(
    [Parameter(Mandatory=$true)][string]$Serial,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$adb = Join-Path $env:LOCALAPPDATA 'Android/Sdk/platform-tools/adb.exe'
$identity = @(& $adb -s $Serial shell getprop ro.boot.serialno)
if ($LASTEXITCODE -ne 0 -or ($identity -join '').Trim() -ne '603ac302') {
    throw 'Expected the previously identified reference tablet 603ac302; no capture performed.'
}
$kernel = @(& $adb -s $Serial shell uname -r)
if ($LASTEXITCODE -ne 0 -or ($kernel -join '') -notmatch '^5\.15\.') {
    throw 'Reference kernel is not 5.15; no capture performed.'
}
if (Test-Path -LiteralPath $OutputDirectory) { throw 'Use a new output directory.' }
New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
# Read-only shell commands. No push, properties, settings, modesets, or log clearing.
$commands = [ordered]@{
    'identity.txt' = 'getprop ro.boot.serialno; uname -a; getprop ro.build.fingerprint; getprop ro.vendor.build.fingerprint; id'
    'display.txt' = 'dumpsys display'
    'surfaceflinger.txt' = 'dumpsys SurfaceFlinger'
    'kernel.txt' = 'dmesg | tail -n 1800'
    'logcat.txt' = 'logcat -b all -d -t 2500'
    'dp-debug.txt' = 'cat /sys/kernel/debug/drm_dp/dp_debug'
    'clock-summary.txt' = 'cat /sys/kernel/debug/clk/clk_summary'
    'properties.txt' = 'getprop | grep -iE "display|surface_flinger|debug.sf|dp_"'
}
$receipts = @()
foreach ($entry in $commands.GetEnumerator()) {
    # adb exec-out returns device permission errors as evidence; never auto-root reference.
    $result = @(& $adb -s $Serial shell $entry.Value 2>&1)
    $code = $LASTEXITCODE
    $result | Set-Content -LiteralPath (Join-Path $OutputDirectory $entry.Key) -Encoding utf8
    $receipts += [pscustomobject]@{ file=$entry.Key; command=$entry.Value; exit_code=$code }
}
$receipts | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputDirectory 'commands.json') -Encoding utf8
Write-Output "Saved read-only reference capture: $OutputDirectory"
