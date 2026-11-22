param(
    [Parameter(Mandatory = $true)][string]$Serial
)
# Restore only the two existing volatile trials; never flash or switch slots.
$ErrorActionPreference = 'Stop'
$adb = Join-Path $env:LOCALAPPDATA 'Android\Sdk\platform-tools\adb.exe'
function Invoke-AdbChecked {
    param([string[]]$Arguments)
    & $adb -s $Serial @Arguments
    if ($LASTEXITCODE -ne 0) { throw "ADB failed: $($Arguments -join ' ')" }
}
$identity = & $adb -s $Serial shell getprop ro.serialno
if ($LASTEXITCODE -ne 0 -or "$identity".Trim() -ne 'ca10ede3') {
    throw 'Target offline or not ca10ede3; nothing changed.'
}
$slot = & $adb -s $Serial shell getprop ro.boot.slot_suffix
if ($LASTEXITCODE -ne 0 -or "$slot".Trim() -ne '_b') { throw 'Unexpected slot.' }
$boot = & $adb -s $Serial shell getprop sys.boot_completed
if ($LASTEXITCODE -ne 0 -or "$boot".Trim() -ne '1') { throw 'Android not ready.' }
foreach ($name in @('trial_sheng_desktop_systemui.sh', 'trial_sheng_dp_core.sh')) {
    $local = Join-Path $PSScriptRoot $name
    $remote = "/data/local/tmp/$name"
    Invoke-AdbChecked -Arguments @('push', $local, $remote)
    Invoke-AdbChecked -Arguments @('shell', 'chmod', '0700', $remote)
    # Each device script checks its exact baseline/candidate and owns rollback.
    Invoke-AdbChecked -Arguments @('shell', 'su', '-c', $remote)
}
Write-Output 'Both temporary trials loaded; visual acceptance still required.'
