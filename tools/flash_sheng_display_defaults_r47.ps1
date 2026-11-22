param([switch]$Flash)
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$batch = Join-Path $workspace 'artifacts/system-hardware-followup-sheng-r47'
$review = Get-Content -Raw (Join-Path $batch 'build-result.json') | ConvertFrom-Json
if ($review.revision -ne 47 -or -not $review.complete_avb_chain_verified -or
    -not $review.all_filesystem_stages_verified -or -not $review.original_systemui_unchanged -or
    -not $review.normal_module_build_passed -or -not $review.policy_and_vintf_unchanged_from_r45 -or
    -not $review.first_setup_seed_144 -or $review.face_r46_installed) { throw 'Unverified r47 batch.' }
if ((($review.files.partition | Sort-Object) -join ',') -ne 'odm,system_ext,vbmeta,vbmeta_system') {
    throw 'Wrong partition scope.'
}
$images = @{}
foreach ($entry in $review.files) {
    if ($entry.name -ne ($entry.partition + '.img')) { throw 'Wrong image name.' }
    $path = Join-Path $batch $entry.name
    if ((Get-Item $path).Length -ne $entry.bytes -or
        (Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) {
        throw "Changed image: $($entry.partition)"
    }
    $images[$entry.partition] = $path
}
$evidence = Join-Path $workspace 'reports/device/20261111-simple'
New-Item -ItemType Directory -Force $evidence | Out-Null
$adb = Join-Path $workspace 'tools/platform-tools/adb.exe'
$fastboot = Join-Path $workspace 'tools/platform-tools/fastboot.exe'
$log = Join-Path $evidence 'flash-operations.txt'
function Invoke-Target([string]$tool, [string[]]$arguments) {
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $tool
    $start.WorkingDirectory = $workspace
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($argument in (@('-s', 'ca10ede3') + $arguments)) { $start.ArgumentList.Add($argument) }
    Add-Content $log ((Get-Date -Format o) + ' ' + [IO.Path]::GetFileName($tool) + ' ' + ($arguments -join ' '))
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    if (-not $process.Start()) { throw 'Tool failed to start.' }
    $stdout, $stderr = $process.StandardOutput.ReadToEndAsync(), $process.StandardError.ReadToEndAsync()
    $timeout = if ($arguments[0] -eq 'flash') { 300000 } else { 20000 }
    if (-not $process.WaitForExit($timeout)) { $process.Kill(); throw 'Device tool timeout.' }
    $output, $code = ($stdout.Result + "`n" + $stderr.Result), $process.ExitCode
    $process.Dispose()
    Add-Content $log $output
    if ($code -ne 0) { throw $output }
    return $output
}
function Assert-Fastboot([bool]$userspace) {
    if ((Invoke-Target $fastboot @('getvar','product')) -notmatch '(?m)^product:\s*sheng\s*$' -or
        (Invoke-Target $fastboot @('getvar','current-slot')) -notmatch '(?m)^current-slot:\s*a\s*$') {
        throw 'Fastboot target/slot mismatch.'
    }
    $expected = if ($userspace) { 'yes' } else { 'no' }
    if ((Invoke-Target $fastboot @('getvar','is-userspace')) -notmatch ('(?m)^is-userspace:\s*'+$expected+'\s*$')) {
        throw 'Wrong fastboot mode.'
    }
}
function Wait-Fastboot([bool]$userspace) {
    $deadline = (Get-Date).AddSeconds(120)
    do {
        Start-Sleep -Seconds 3
        try { Assert-Fastboot $userspace; return } catch { $lastFailure = $_ }
    } while ((Get-Date) -lt $deadline)
    throw $lastFailure
}
if ((Invoke-Target $adb @('shell','getprop ro.build.fingerprint')).Trim() -ne
    'Xiaomi/lineage_sheng/sheng:17/CP2A.260605.016/eng.root:userdebug/test-keys' -or
    (Invoke-Target $adb @('shell','getprop ro.boot.slot_suffix')).Trim() -ne '_a' -or
    (Invoke-Target $adb @('shell','getprop sys.boot_completed')).Trim() -ne '1' -or
    (Invoke-Target $adb @('shell','getprop ro.boot.flash.locked')).Trim() -ne '0' -or
    (Invoke-Target $adb @('shell','id -u')).Trim() -ne '0') { throw 'Expected rooted, unlocked A-slot tablet.' }
foreach ($p in @('odm','system_ext','vbmeta','vbmeta_system')) {
    $command = if ($p -in @('odm','system_ext')) { "sha256sum /dev/block/mapper/${p}_a" }
               else { "head -c $((Get-Item $images[$p]).Length) /dev/block/by-name/${p}_a | sha256sum" }
    $actual = ((Invoke-Target $adb @('shell',$command)).Trim() -split '\s+')[0]
    if ($actual -ne $review.baseline_sha256.$p) { throw "Unexpected live baseline: $p" }
}
Write-Output 'r47 images and installed A-slot r45 baseline verified.'
if (-not $Flash) { return }
Invoke-Target $adb @('reboot','fastboot') | Write-Output
Wait-Fastboot $true
foreach ($p in @('odm','system_ext')) {
    Invoke-Target $fastboot @('flash',($p+'_a'),$images[$p]) | Write-Output
}
Invoke-Target $fastboot @('reboot','bootloader') | Write-Output
Wait-Fastboot $false
if ((Invoke-Target $fastboot @('getvar','unlocked')) -notmatch '(?m)^unlocked:\s*yes\s*$') {
    throw 'Locked bootloader.'
}
foreach ($p in @('vbmeta','vbmeta_system')) {
    Invoke-Target $fastboot @('flash',($p+'_a'),$images[$p]) | Write-Output
}
Invoke-Target $fastboot @('reboot') | Write-Output
Write-Output 'Four verified r47 images written to A; runtime verification remains required.'
