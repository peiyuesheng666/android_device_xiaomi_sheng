param([switch]$Flash)
# Read-only preflight by default; -Flash installs the reviewed control-label fix.
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7 required.' }
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$batch = Join-Path $workspace 'artifacts/system-hardware-followup-sheng-r62'
$previousPath = Join-Path $workspace 'artifacts/system-hardware-followup-sheng-r61/build-result.json'
$review = Get-Content -LiteralPath (Join-Path $batch 'build-result.json') -Raw | ConvertFrom-Json
$previous = Get-Content -LiteralPath $previousPath -Raw | ConvertFrom-Json
$evidence = Join-Path $workspace 'reports/device/20261112-fingerprint-regression'
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
$log = Join-Path $evidence ('flash-r62-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.txt')
$adb = Join-Path $workspace 'tools/platform-tools/adb.exe'
$fastboot = Join-Path $workspace 'tools/platform-tools/fastboot.exe'

function Assert-Hash([object]$value, [string]$label) {
    if ([string]$value -cnotmatch '^[0-9a-f]{64}$') { throw "Invalid hash: $label" }
}
function Assert-File([string]$path, [object]$bytes, [string]$digest) {
    Assert-Hash $digest $path
    $item = Get-Item -LiteralPath $path
    if ($item.PSIsContainer -or ($null -ne $bytes -and $item.Length -ne [long]$bytes) -or
        (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $digest) {
        throw "Changed file: $path"
    }
}
function Assert-Set([object[]]$actual, [string[]]$expected, [string]$label) {
    if ($actual.Count -ne $expected.Count -or
        (($actual | Sort-Object) -join ',') -cne (($expected | Sort-Object) -join ',')) { throw "Unexpected $label" }
}
function Assert-Entry([object]$entry) {
    if ([string]$entry.partition -cnotmatch '^[a-z_]+$' -or
        [string]$entry.name -cne ([string]$entry.partition + '.img') -or
        [string]$entry.bytes -cnotmatch '^[1-9][0-9]*$') { throw 'Invalid partition entry.' }
    Assert-Hash $entry.sha256 $entry.partition
}
if ($review.revision -ne 62 -or $review.baseline_revision -ne 61 -or $previous.revision -ne 61) {
    throw 'Wrong revision.'
}
Assert-File $previousPath $null $review.baseline_manifest_sha256
foreach ($field in @('original_systemui_unchanged','complete_avb_chain_verified',
    'all_filesystem_stages_verified','normal_module_build_passed','installed_qti_retained',
    'fingerprint_control_label_corrected','no_new_allow_rules','compiled_genfs_lookup_passed')) {
    if ($review.$field -cne $true) { throw "Missing verification: $field" }
}
if ($review.qti_source_service_integrated -cne $false -or $review.face_candidate_installed -cne $false -or
    $review.recovery_revision_retained -ne 59) { throw 'Unexpected service or Recovery change.' }
$controlRule = '(genfscon sysfs "/devices/platform/soc/soc:fingerprint_fpc/wakeup_enable" (u object_r sysfs_fingerprint_sheng ((s0) (s0))))'
Assert-Set @($review.policy_added) @($controlRule) 'policy delta'
Assert-Set @($review.files.partition) @('vendor','vbmeta') 'flashed partitions'
$allowed = @('system','odm','product','system_ext','vendor','vendor_dlkm','system_dlkm',
    'init_boot','boot','dtbo','recovery','vendor_boot','vbmeta','vbmeta_system')
$baseline = @($previous.files) + @($previous.unchanged_partition_files) + @($previous.unchanged_boot_dependencies)
foreach ($entry in $baseline) {
    if ($null -eq $entry.name) { $entry | Add-Member NoteProperty name ($entry.partition + '.img') }
    Assert-Entry $entry
}
Assert-Set @($baseline.partition) $allowed 'sealed baseline partitions'
Assert-Set @($review.baseline_partitions.partition) $allowed 'candidate baseline partitions'
foreach ($entry in $review.baseline_partitions) {
    Assert-Entry $entry
    $sealed = @($baseline | Where-Object partition -CEQ $entry.partition)
    if ($sealed.Count -ne 1 -or $sealed[0].bytes -ne $entry.bytes -or $sealed[0].sha256 -cne $entry.sha256) {
        throw 'Candidate baseline differs from sealed r61.'
    }
}
Assert-Set @($review.unchanged_partition_files.partition) @($allowed | Where-Object { $_ -cnotin @('vendor','vbmeta') }) 'retained partitions'
foreach ($entry in $review.unchanged_partition_files) {
    Assert-Entry $entry
    $sealed = @($baseline | Where-Object partition -CEQ $entry.partition)
    if ($sealed[0].bytes -ne $entry.bytes -or $sealed[0].sha256 -cne $entry.sha256) { throw 'Retained dependency changed.' }
}
Assert-Set @($review.sources_sha256.PSObject.Properties.Name) @('device/xiaomi/sheng/sepolicy/vendor/genfs_contexts') 'source scope'
Assert-File (Join-Path $workspace 'device/xiaomi/sheng/sepolicy/vendor/genfs_contexts') $null $review.sources_sha256.'device/xiaomi/sheng/sepolicy/vendor/genfs_contexts'
Assert-Set @($review.entries.vendor.PSObject.Properties.Name) @('etc/selinux/vendor_sepolicy.cil') 'vendor file scope'
$policyEntry = $review.entries.vendor.'etc/selinux/vendor_sepolicy.cil'
Assert-Hash $policyEntry.sha256 'packaged policy'
if ($review.boot_policy.actual_partition_neverallows_passed -cne $true -or
    $review.boot_policy.actual_partition_combination_compiled -cne $true -or
    $review.boot_policy.split_policy_selected_by_partition_hashes -cne $true) { throw 'Actual boot policy not validated.' }
$policyHashes = @($review.boot_policy.input_sha256.PSObject.Properties | Where-Object { $_.Name.EndsWith('/vendor_sepolicy.cil') })
if ($policyHashes.Count -ne 1 -or $policyHashes[0].Value -cne $policyEntry.sha256) { throw 'Policy receipt uses a different input.' }
$images = @{}
foreach ($entry in $review.files) {
    Assert-Entry $entry
    $path = Join-Path $batch $entry.name
    Assert-File $path $entry.bytes $entry.sha256
    $images[$entry.partition] = $path
}
function Invoke-Target([string]$tool, [string[]]$arguments) {
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $tool
    $start.WorkingDirectory = $workspace
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($argument in (@('-s','ca10ede3') + $arguments)) { $start.ArgumentList.Add($argument) }
    Add-Content -LiteralPath $log ((Get-Date -Format o) + ' ' + [IO.Path]::GetFileName($tool) + ' ' + ($arguments | ConvertTo-Json -Compress))
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    if (-not $process.Start()) { throw 'Device tool failed.' }
    $stdout, $stderr = $process.StandardOutput.ReadToEndAsync(), $process.StandardError.ReadToEndAsync()
    $timeout = if ($arguments[0] -ceq 'flash') { 300000 } elseif ($arguments[0] -ceq 'shell') { 60000 } else { 20000 }
    if (-not $process.WaitForExit($timeout)) { $process.Kill(); $process.Dispose(); throw 'Device tool timeout.' }
    $output, $code = ($stdout.Result + "`n" + $stderr.Result), $process.ExitCode
    $process.Dispose()
    Add-Content -LiteralPath $log $output
    if ($code -ne 0) { throw $output }
    return $output
}
function Assert-Fastboot([bool]$userspace) {
    $expected = if ($userspace) { 'yes' } else { 'no' }
    if ((Invoke-Target $fastboot @('getvar','product')) -cnotmatch '(?m)^product:\s*sheng\s*$' -or
        (Invoke-Target $fastboot @('getvar','current-slot')) -cnotmatch '(?m)^current-slot:\s*a\s*$' -or
        (Invoke-Target $fastboot @('getvar','is-userspace')) -cnotmatch ('(?m)^is-userspace:\s*' + $expected + '\s*$')) {
        throw 'Wrong fastboot device, slot or mode.'
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
foreach ($check in @(@('ro.product.device','sheng'),@('ro.boot.slot_suffix','_a'),
    @('sys.boot_completed','1'),@('ro.boot.flash.locked','0'))) {
    if ((Invoke-Target $adb @('shell','getprop',$check[0])).Trim() -cne $check[1]) { throw 'Unexpected live device.' }
}
if ((Invoke-Target $adb @('shell','id','-u')).Trim() -cne '0' -or
    (Invoke-Target $adb @('shell','getenforce')).Trim() -cne 'Enforcing') { throw 'Rooted Enforcing device required.' }
foreach ($entry in $baseline) {
    $part = [string]$entry.partition
    $taskArguments = if ($part -cin @('system','odm','product','system_ext','vendor','vendor_dlkm','system_dlkm')) {
        @('shell','sha256sum',('/dev/block/mapper/' + $part + '_a'))
    } else {
        @('shell',('head -c ' + [long]$entry.bytes + ' /dev/block/by-name/' + $part + '_a | sha256sum'))
    }
    if (((Invoke-Target $adb $taskArguments).Trim() -split '\s+')[0] -cne $entry.sha256) { throw "Live baseline mismatch: $part" }
}
$qti = ((Invoke-Target $adb @('shell','sha256sum','/vendor/bin/hw/vendor.qti.media.c2@1.0-service')).Trim() -split '\s+')[0]
if ($qti -cne $review.retained_qti_sha256 -or $qti -cne $previous.retained_qti_sha256) { throw 'QTI baseline changed.' }
Write-Output 'r62 package, exact policy scope and all 14 r61 baseline partitions verified.'
if (-not $Flash) { return }
Invoke-Target $adb @('reboot','fastboot') | Write-Output
Wait-Fastboot $true
Invoke-Target $fastboot @('flash','vendor_a',$images['vendor']) | Write-Output
Invoke-Target $fastboot @('reboot','bootloader') | Write-Output
Wait-Fastboot $false
if ((Invoke-Target $fastboot @('getvar','unlocked')) -cnotmatch '(?m)^unlocked:\s*yes\s*$') { throw 'Locked bootloader.' }
Invoke-Target $fastboot @('flash','vbmeta_a',$images['vbmeta']) | Write-Output
Invoke-Target $fastboot @('reboot') | Write-Output
Write-Output 'r62 vendor and vbmeta written to A; postboot verification is required.'
