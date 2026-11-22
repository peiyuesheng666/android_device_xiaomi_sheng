param([switch]$Flash, [ValidateSet(48,49)][int]$Revision = 48)
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$batch = Join-Path $workspace "artifacts/system-hardware-followup-sheng-r$Revision"
$review = Get-Content -Raw (Join-Path $batch 'build-result.json') | ConvertFrom-Json
if ($Revision -eq 48 -and ($review.revision -ne 48 -or -not $review.complete_avb_chain_verified -or
    -not $review.all_filesystem_stages_verified -or -not $review.original_systemui_unchanged -or
    -not $review.normal_module_build_passed -or -not $review.boot_policy.actual_partition_combination_compiled -or -not $review.vintf.actual_partition_combination_compatible -or -not $review.bluetooth_lhdc_software_route -or -not $review.usb_standard_rndis -or -not $review.touch_stock_mode14 -or
    -not $review.first_setup_seed_144 -or $review.face_r46_installed -or
    -not $review.boot_policy.actual_partition_neverallows_passed -or
    -not $review.touch_report_240_candidate -or -not $review.matching_product_policy_verified -or
    -not $review.product_policy_review.original_rule_statements_unchanged -or
    $review.entries.odm.'firmware/n81a_nova_thp_config.ini'.sha256 -ne
    '9ba104e0ea2bd9c4b843e11989607be5de3a8c107f6d92b3a0a596bf39d64f2c')) { throw 'Unverified r48 batch.' }
if ($Revision -eq 49 -and ($review.revision -ne 49 -or $review.baseline_revision -ne 48 -or
    -not $review.complete_avb_chain_verified -or -not $review.all_filesystem_stages_verified -or
    -not $review.original_systemui_unchanged -or -not $review.normal_module_build_passed -or
    -not $review.original_thp_restored -or -not $review.policy_unchanged_from_strict_r48 -or
    -not $review.vintf_unchanged_from_verified_r48 -or
    $review.original_thp_sha256 -ne 'cb75e8cf9128f9ea6177d8276d440dc16f55db8f068f7644e94668cfc8f6e2c5')) {
    throw 'Unverified THP restoration.'
}
$expectedScope = if ($Revision -eq 48) { 'odm,product,system_ext,vbmeta,vbmeta_system,vendor' } else { 'odm,vbmeta' }
if ((($review.files.partition | Sort-Object) -join ',') -ne $expectedScope) {
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
$log = Join-Path $evidence "flash-r$Revision-operations.txt"
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
foreach ($p in @('odm','product','system_ext','vendor','vbmeta','vbmeta_system')) {
    $verificationEntries = @($review.files) + @($review.unchanged_partition_files | Where-Object { $_ })
    $verificationEntry = @($verificationEntries | Where-Object partition -eq $p)
    if ($verificationEntry.Count -ne 1) { throw 'Missing or duplicated partition receipt.' }
    $command = if ($p -in @('odm','product','system_ext','vendor')) { "sha256sum /dev/block/mapper/${p}_a" }
               else { "head -c $($verificationEntry[0].bytes) /dev/block/by-name/${p}_a | sha256sum" }
    $actual = ((Invoke-Target $adb @('shell',$command)).Trim() -split '\s+')[0]
    if ($actual -ne $review.baseline_sha256.$p) { throw "Unexpected live baseline: $p" }
}
Write-Output "r$Revision images and installed A-slot baseline verified."
if (-not $Flash) { return }
Invoke-Target $adb @('reboot','fastboot') | Write-Output
Wait-Fastboot $true
$logicalPartitions = if ($Revision -eq 48) { @('odm','product','system_ext','vendor') } else { @('odm') }
foreach ($p in $logicalPartitions) {
    Invoke-Target $fastboot @('flash',($p+'_a'),$images[$p]) | Write-Output
}
Invoke-Target $fastboot @('reboot','bootloader') | Write-Output
Wait-Fastboot $false
if ((Invoke-Target $fastboot @('getvar','unlocked')) -notmatch '(?m)^unlocked:\s*yes\s*$') {
    throw 'Locked bootloader.'
}
$physicalPartitions = if ($Revision -eq 48) { @('vbmeta','vbmeta_system') } else { @('vbmeta') }
foreach ($p in $physicalPartitions) {
    Invoke-Target $fastboot @('flash',($p+'_a'),$images[$p]) | Write-Output
}
Invoke-Target $fastboot @('reboot') | Write-Output
Write-Output "$($review.files.Count) verified r$Revision images written to A; runtime verification remains required."
