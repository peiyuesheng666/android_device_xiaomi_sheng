# Camera-free native Face protocol checks. No installation, registration or settings changes.
param(
    [string]$ArtifactDirectory = '',
    [switch]$Hardware
)
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$adb = Join-Path $workspace 'tools/platform-tools/adb.exe'
if (-not $ArtifactDirectory) {
    $ArtifactDirectory = Join-Path $workspace 'reports/device/20261110-resume/face-native'
}
$jar = Join-Path $ArtifactDirectory 'ShengNativeFaceProtocolProbe.jar'
if (-not (Test-Path -LiteralPath $jar)) { throw 'Copy the final normal Soong probe JAR first.' }
function Read-Target([string]$command) {
    $value = & $adb -s ca10ede3 shell $command 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Target command failed: $value" }
    return ($value -join "`n").Trim()
}
if ((Read-Target 'id -u') -ne '0' -or
    (Read-Target 'getprop ro.product.device') -ne 'sheng' -or
    (Read-Target 'getprop ro.boot.slot_suffix') -ne '_a' -or
    (Read-Target 'getprop sys.boot_completed') -ne '1' -or
    (Read-Target 'getenforce') -ne 'Enforcing') {
    throw 'Expected rooted ca10ede3 sheng A slot, booted and Enforcing.'
}
$originalSystemUI = '33017b0d59e28da5db3e089a98f49601de508228a012392ee2d04c82cda3ccb1'
$systemUI = ((Read-Target 'sha256sum /system_ext/priv-app/SystemUI/SystemUI.apk') -split '\s+')[0]
if ($systemUI -ne $originalSystemUI) { throw 'Original SystemUI changed.' }
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $jar).Hash.ToLowerInvariant()
& $adb -s ca10ede3 push $jar /data/local/tmp/sheng-native-face-probe.jar
if ($LASTEXITCODE -ne 0) { throw 'Probe push failed.' }
$remoteHash = ((Read-Target 'sha256sum /data/local/tmp/sheng-native-face-probe.jar') -split '\s+')[0]
if ($remoteHash -ne $hash) { throw 'Probe readback hash mismatch.' }
foreach ($class in @('NativeFaceProtocolProbe', 'NativeFaceSessionProbe')) {
    $option = if ($Hardware -and $class -eq 'NativeFaceProtocolProbe') { ' --hardware' } else { '' }
    $command = '/system/bin/app_process -Djava.class.path=/data/local/tmp/sheng-native-face-probe.jar:/system/framework/services.jar /system/bin org.lineageos.sheng.face.' + $class + $option
    $result = Read-Target $command
    [IO.File]::WriteAllText((Join-Path $ArtifactDirectory ("runtime-$class.txt")), $result + "`n")
    Write-Output $result
    if ($result -notmatch 'checks passed; camera not opened') { throw "Probe did not pass: $class" }
    if ($Hardware -and $class -eq 'NativeFaceProtocolProbe' -and
        $result -notmatch 'KEY_USER_NOT_AUTHENTICATED') { throw 'Hardware rejection was not confirmed.' }
}
$after = ((Read-Target 'sha256sum /system_ext/priv-app/SystemUI/SystemUI.apk') -split '\s+')[0]
if ($after -ne $originalSystemUI -or (Read-Target 'getenforce') -ne 'Enforcing') {
    throw 'Post-test original SystemUI/Enforcing check failed.'
}
$receipt = [ordered]@{
    date = (Get-Date -Format o)
    target = 'ca10ede3'; slot = 'a'; artifact = $hash
    original_systemui_sha256 = $after; selinux = 'Enforcing'
    camera_opened_by_agent = $false; biometric_service_registered = $false
    settings_changed = $false; templates_enrolled = $false
    transport_and_synthetic_session_passed = $true; hardware_negative_tests_passed = [bool]$Hardware
    genuine_credential_hat_positive_tested = $false
    native_settings_enrollment_tested = $false; keyguard_authentication_tested = $false
}
[IO.File]::WriteAllText((Join-Path $ArtifactDirectory 'runtime-review.json'), ($receipt | ConvertTo-Json) + "`n")
