# Exercise the installed receiver in a disposable background Android user.
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$adb = Join-Path $workspace 'tools/platform-tools/adb.exe'
$evidence = Join-Path $workspace 'reports/device/20261111-simple'
New-Item -ItemType Directory -Force $evidence | Out-Null
$log = Join-Path $evidence 'refresh-user-trials.txt'
function Invoke-Adb([string[]]$Arguments) {
    $output = (& $adb -s ca10ede3 @Arguments 2>&1 | Out-String).Trim()
    $code = $LASTEXITCODE
    Add-Content $log ((Get-Date -Format o) + ' ' + ($Arguments -join ' ') + "`n" + $output)
    if ($code -ne 0) { throw $output }
    return $output
}
function Get-Setting([string]$name) {
    return Invoke-Adb @('shell','settings','--user',"$trialUser",'get','system',$name)
}
function Set-Setting([string]$name, [string]$value) {
    Invoke-Adb @('shell','settings','--user',"$trialUser",'put','system',$name,$value) | Out-Null
}
function Assert-Rates([float]$minimum, [float]$peak) {
    $actualMin = Get-Setting 'min_refresh_rate'
    $actualPeak = Get-Setting 'peak_refresh_rate'
    if ([float]$actualMin -ne $minimum -or [float]$actualPeak -ne $peak) {
        throw "Expected $minimum/$peak, got $actualMin/$actualPeak"
    }
}
function Send-Boot([string]$action='android.intent.action.BOOT_COMPLETED') {
    Invoke-Adb @('shell','am','broadcast','--user',"$trialUser",'--include-stopped-packages',
        '-a',$action,'-n','org.lineageos.sheng.displaydefaults/.DefaultRefreshReceiver') | Out-Null
}
if ((Invoke-Adb @('shell','id','-u')) -ne '0' -or
    (Invoke-Adb @('shell','getprop','ro.boot.slot_suffix')) -ne '_a' -or
    (Invoke-Adb @('shell','getprop','ro.build.fingerprint')) -ne
    'Xiaomi/lineage_sheng/sheng:17/CP2A.260605.016/eng.root:userdebug/test-keys') {
    throw 'Wrong test target.'
}
if ((Invoke-Adb @('shell','dumpsys','package','org.lineageos.sheng.displaydefaults')) -notmatch 'versionCode=2\b') {
    throw 'Expected installed defaults version 2.'
}
$ownerBefore = @(
    Invoke-Adb @('shell','settings','--user','0','get','system','min_refresh_rate')
    Invoke-Adb @('shell','settings','--user','0','get','system','peak_refresh_rate')
)
$currentBefore = Invoke-Adb @('shell','am','get-current-user')
if ($currentBefore -ne '0') { throw 'Owner must remain the foreground user.' }
$trialUser = $null
$checks = [Collections.Generic.List[string]]::new()
try {
    $created = Invoke-Adb @('shell','pm','create-user','Sheng-refresh-r47-validation')
    if ($created -notmatch 'Success: created user id (\d+)') { throw $created }
    $trialUser = [int]$Matches[1]
    if ($trialUser -le 0) { throw 'Invalid disposable user id.' }
    Set-Setting 'min_refresh_rate' '60.0'
    Set-Setting 'peak_refresh_rate' '60.0'
    Invoke-Adb @('shell','settings','--user',"$trialUser",'put','secure','user_setup_complete','0') | Out-Null
    Invoke-Adb @('shell','am','start-user','-w',"$trialUser") | Out-Null
    Send-Boot
    Assert-Rates 144 144
    $checks.Add('New user: pre-existing 60/60 initialized to 144/144')
    Set-Setting 'min_refresh_rate' '60.0'
    Set-Setting 'peak_refresh_rate' '90.0'
    Send-Boot 'android.intent.action.LOCKED_BOOT_COMPLETED'
    Send-Boot
    Assert-Rates 60 90
    $checks.Add('Second broadcasts preserve a new user choice during incomplete setup')
    Invoke-Adb @('shell','am','stop-user','-w',"$trialUser") | Out-Null
    Invoke-Adb @('shell','am','start-user','-w',"$trialUser") | Out-Null
    Send-Boot
    Assert-Rates 60 90
    $checks.Add('Initialization marker survives stop/start of the disposable user')
    Invoke-Adb @('shell','settings','--user',"$trialUser",'put','secure','user_setup_complete','1') | Out-Null
    # Reset only this disposable user's initializer data to model an older
    # installed receiver that has never created the new marker.
    $cleared = Invoke-Adb @('shell','pm','clear','--user',"$trialUser",'org.lineageos.sheng.displaydefaults')
    if ($cleared -ne 'Success') { throw $cleared }
    Send-Boot
    Assert-Rates 60 90
    $checks.Add('Completed user without a marker preserves 60/90 on upgrade')
    Invoke-Adb @('shell','settings','--user',"$trialUser",'delete','system','min_refresh_rate') | Out-Null
    Send-Boot
    Assert-Rates 144 90
    $checks.Add('Missing row initialized without replacing the other explicit value')
} finally {
    if ($null -ne $trialUser -and $trialUser -gt 0) {
        $removed = Invoke-Adb @('shell','pm','remove-user',"$trialUser")
        if ($removed -notmatch '^Success') { throw "Could not remove disposable user: $removed" }
        $deadline = (Get-Date).AddSeconds(20)
        do {
            $users = Invoke-Adb @('shell','cmd','user','list','-v','--all')
            if ($users -notmatch "(?m)^\d+: id=${trialUser},") { break }
            Start-Sleep -Seconds 1
        } while ((Get-Date) -lt $deadline)
        if ($users -match "(?m)^\d+: id=${trialUser},") { throw 'Disposable-user removal still pending.' }
    }
}
$ownerAfter = @(
    Invoke-Adb @('shell','settings','--user','0','get','system','min_refresh_rate')
    Invoke-Adb @('shell','settings','--user','0','get','system','peak_refresh_rate')
)
if (($ownerBefore -join ',') -ne ($ownerAfter -join ',') -or
    (Invoke-Adb @('shell','am','get-current-user')) -ne $currentBefore) {
    throw 'Owner settings or foreground user changed.'
}
$checks.Add('Owner settings and foreground user unchanged; disposable user removed')
@{ passed=$true; checks=@($checks); ownerBefore=$ownerBefore; ownerAfter=$ownerAfter;
   disposableUser=$trialUser; factoryResetTested=$false } | ConvertTo-Json -Depth 4 |
    Set-Content -Encoding utf8 (Join-Path $evidence 'refresh-user-trials.json')
$checks
