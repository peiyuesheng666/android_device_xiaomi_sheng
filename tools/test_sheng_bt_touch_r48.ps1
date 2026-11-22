# Read back the installed batch without starting camera or changing settings.
param([ValidateSet(48,49)][int]$Revision = 48)
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$adb = Join-Path $workspace 'tools/platform-tools/adb.exe'
$batch = Join-Path $workspace "artifacts/system-hardware-followup-sheng-r$Revision"
$review = Get-Content -Raw (Join-Path $batch 'build-result.json') | ConvertFrom-Json
$evidence = Join-Path $workspace 'reports/device/20261111-simple'
$log = Join-Path $evidence "r$Revision-runtime-readback.txt"
New-Item -ItemType Directory -Force $evidence | Out-Null
function Invoke-Adb([string[]]$Arguments) {
    $output = (& $adb -s ca10ede3 @Arguments 2>&1 | Out-String).Trim()
    Add-Content $log (($Arguments -join ' ') + "`n" + $output)
    if ($LASTEXITCODE -ne 0) { throw $output }
    return $output
}
if ($review.revision -ne $Revision -or -not $review.complete_avb_chain_verified -or
    (Invoke-Adb @('shell','getprop ro.boot.slot_suffix')) -ne '_a' -or
    (Invoke-Adb @('shell','id -u')) -ne '0' -or
    (Invoke-Adb @('shell','getprop sys.boot_completed')) -ne '1' -or
    (Invoke-Adb @('shell','getenforce')) -ne 'Enforcing') { throw 'Wrong target/runtime.' }
$bootId = Invoke-Adb @('shell','cat /proc/sys/kernel/random/boot_id')
$processes = Invoke-Adb @('shell','pidof system_server surfaceflinger com.android.systemui')
$checks = [Collections.Generic.List[string]]::new()
foreach ($entry in (@($review.files) + @($review.unchanged_partition_files | Where-Object { $_ }))) {
    $part = $entry.partition
    if ($part -notin @('vendor','odm','product','system_ext','vbmeta','vbmeta_system')) { throw 'Unexpected partition.' }
    $command = if ($part -in @('vendor','odm','product','system_ext')) { "sha256sum /dev/block/mapper/${part}_a" }
               else { "head -c $($entry.bytes) /dev/block/by-name/${part}_a | sha256sum" }
    $actual = ((Invoke-Adb @('shell',$command)) -split '\s+')[0]
    if ($actual -ne $entry.sha256) { throw "Partition mismatch: $part" }
    $checks.Add("$part partition SHA256 matches sealed image")
}
foreach ($partition in $review.entries.PSObject.Properties) {
    foreach ($entry in $partition.Value.PSObject.Properties) {
        $relative = $entry.Name
        if ($relative -notmatch '^[A-Za-z0-9_./+-]+$' -or $relative.Contains('..')) { throw 'Invalid payload path.' }
        $path = '/' + $partition.Name + '/' + $relative
        $actual = ((Invoke-Adb @('shell',"sha256sum $path")) -split '\s+')[0]
        if ($actual -ne $entry.Value.sha256) { throw "Payload mismatch: $path" }
    }
}
$checks.Add('All declared installed payload files match normal build outputs')
$ui = ((Invoke-Adb @('shell','sha256sum /system_ext/priv-app/SystemUI/SystemUI.apk')) -split '\s+')[0]
if ($ui -ne '33017b0d59e28da5db3e089a98f49601de508228a012392ee2d04c82cda3ccb1') { throw 'SystemUI changed.' }
if ((Invoke-Adb @('shell','getprop vendor.usb.rndis.func.name')) -ne 'rndis') { throw 'Wrong USB function selection.' }
if ((Invoke-Adb @('shell','dumpsys package org.lineageos.sheng.displaydefaults')) -notmatch 'versionCode=2\b') {
    throw 'Display initializer version mismatch.'
}
if (-not (Invoke-Adb @('shell','pidof com.xiaomi.sheng.touch'))) { throw 'Touch synchronization app not running.' }
if (-not (Invoke-Adb @('shell','pidof sheng-touch-report'))) { throw 'Stock THP report service stopped.' }
$dpmsLabel = Invoke-Adb @('shell','ls -Z /sys/devices/platform/soc/ae00000.qcom,mdss_mdp/drm/card0/card0-DSI-1/dpms')
$gestureLabel = Invoke-Adb @('shell','ls -Z /proc/xm_htc_gesture_switch')
if ($dpmsLabel -notmatch ':vendor_sysfs_sheng_touch_dpms:' -or
    $gestureLabel -notmatch ':vendor_proc_sheng_touch_gesture:') { throw 'Touch node label mismatch.' }
$touchState = Invoke-Adb @('shell','cat /sys/class/drm/card0-DSI-1/dpms; cat /proc/xm_htc_gesture_switch')
$checks.Add('Original SystemUI, permanent RNDIS property, display version and touch labels verified')
if ((Invoke-Adb @('shell','cat /proc/sys/kernel/random/boot_id')) -ne $bootId -or
    (Invoke-Adb @('shell','pidof system_server surfaceflinger com.android.systemui')) -ne $processes -or
    (Invoke-Adb @('shell','getenforce')) -ne 'Enforcing') { throw 'Framework restarted during verification.' }
@{ passed=$true; checks=@($checks); bootId=$bootId; processes=$processes;
   touchState=$touchState; physicalTouchTested=$false; accessoryAudioAfterRebootTested=$false;
   usbInternetAfterRebootTested=$false } | ConvertTo-Json -Depth 4 |
    Set-Content -Encoding utf8 (Join-Path $evidence "r$Revision-runtime-readback.json")
$checks
