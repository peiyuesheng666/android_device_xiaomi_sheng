param([switch]$Flash)
$Revision = 50
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$batch = Join-Path $workspace 'artifacts/system-hardware-followup-sheng-r50'
$review = Get-Content -Raw (Join-Path $batch 'build-result.json') | ConvertFrom-Json
if ($review.revision -ne 50 -or $review.baseline_revision -ne 49 -or
    -not $review.complete_avb_chain_verified -or -not $review.all_filesystem_stages_verified -or
    -not $review.original_systemui_unchanged -or -not $review.normal_module_build_passed -or
    -not $review.boot_policy.actual_partition_combination_compiled -or
    -not $review.boot_policy.actual_partition_neverallows_passed -or
    -not $review.vintf.actual_partition_combination_compatible -or
    -not $review.high_touch_report_only -or $review.high_touch_report_mode -ne 202 -or
    $review.physical_scan_360_fixed -or $review.face_r46_installed -or
    -not $review.unrelated_settings_overlay_resources_preserved -or
    $review.original_thp_sha256 -ne 'cb75e8cf9128f9ea6177d8276d440dc16f55db8f068f7644e94668cfc8f6e2c5') {
    throw 'Unverified r50 report-rate batch.'
}
$expectedScope = if ($review.product_policy_changed) { 'odm,product,system_ext,vbmeta,vbmeta_system,vendor' }
                 else { 'odm,system_ext,vbmeta,vbmeta_system,vendor' }
if ((($review.files.partition | Sort-Object) -join ',') -ne $expectedScope) {
    throw 'Wrong r50 partition scope.'
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
# The platform cache considers the package directory older than its cached
# result even when a reproducible APK's own mtime changes. Preserve and move
# only this package's parse entry before the next scan; retain all app data.
$cacheEntries = (Invoke-Target $adb @('shell',
    'find /data/system/package_cache -maxdepth 2 -type f -name ShengTouch-16--991899917')).Trim()
foreach ($cacheEntry in ($cacheEntries -split '\r?\n' | Where-Object { $_ })) {
    if ($cacheEntry -notmatch '^/data/system/package_cache/[0-9a-f]{40}/ShengTouch-16--991899917$') {
        throw 'Unexpected package parse-cache path.'
    }
    $stamp = Get-Date -Format 'yyyyMMddHHmmssfff'
    $backup = Join-Path $evidence "r50-ShengTouch-parse-cache-$stamp.bin"
    Invoke-Target $adb @('pull',$cacheEntry,$backup) | Write-Output
    $saved = "/data/local/tmp/r50-ShengTouch-parse-cache-$stamp.bin"
    Invoke-Target $adb @('shell',"test ! -e $saved") | Out-Null
    Invoke-Target $adb @('shell',"mv $cacheEntry $saved") | Out-Null
}
Invoke-Target $adb @('reboot','fastboot') | Write-Output
Wait-Fastboot $true
$logicalPartitions = @('odm','product','system_ext','vendor') | Where-Object { $images.ContainsKey($_) }
foreach ($p in $logicalPartitions) {
    Invoke-Target $fastboot @('flash',($p+'_a'),$images[$p]) | Write-Output
}
Invoke-Target $fastboot @('reboot','bootloader') | Write-Output
Wait-Fastboot $false
if ((Invoke-Target $fastboot @('getvar','unlocked')) -notmatch '(?m)^unlocked:\s*yes\s*$') {
    throw 'Locked bootloader.'
}
$physicalPartitions = @('vbmeta','vbmeta_system')
foreach ($p in $physicalPartitions) {
    Invoke-Target $fastboot @('flash',($p+'_a'),$images[$p]) | Write-Output
}
Invoke-Target $fastboot @('reboot') | Write-Output
Write-Output "$($review.files.Count) verified r$Revision images written to A; runtime verification remains required."
