param([switch]$Flash, [ValidateSet(63,64)][int]$Revision = 63)
# Read-only preflight by default; -Flash installs the normally built pen page.
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7 required.' }
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$batch = Join-Path $workspace "artifacts/system-hardware-followup-sheng-r$Revision"
$previousPath = Join-Path $workspace ('artifacts/system-hardware-followup-sheng-r' + ($Revision - 1) + '/build-result.json')
$review = Get-Content -LiteralPath (Join-Path $batch 'build-result.json') -Raw | ConvertFrom-Json
$previous = Get-Content -LiteralPath $previousPath -Raw | ConvertFrom-Json
$evidence = Join-Path $workspace 'reports/device/20261113-pen-settings'
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
$log = Join-Path $evidence ('flash-r' + $Revision + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.txt')
$adb = Join-Path $workspace 'tools/platform-tools/adb.exe'
$fastboot = Join-Path $workspace 'tools/platform-tools/fastboot.exe'
$app = 'app/ShengPenSettings/ShengPenSettings.apk'
$allowed = @('system','system_ext','product','vendor','odm','vendor_dlkm','system_dlkm',
    'init_boot','boot','dtbo','recovery','vendor_boot','vbmeta','vbmeta_system')
$logical = @('system','system_ext','product','vendor','odm','vendor_dlkm','system_dlkm')

function Assert-File([string]$path, [object]$bytes, [string]$digest) {
    if ($digest -cnotmatch '^[0-9a-f]{64}$') { throw "Invalid hash: $path" }
    $item = Get-Item -LiteralPath $path
    if ($item.PSIsContainer -or ($null -ne $bytes -and $item.Length -ne [long]$bytes) -or
        (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $digest) {
        throw "Changed file: $path"
    }
}
function Assert-Set([object[]]$actual, [string[]]$expected, [string]$label) {
    if ($actual.Count -ne $expected.Count -or
        (($actual | Sort-Object) -join ',') -cne (($expected | Sort-Object) -join ',')) {
        throw "Unexpected $label"
    }
}
function Assert-Entry([object]$entry) {
    if ([string]$entry.partition -cnotin $allowed -or
        [string]$entry.name -cne ([string]$entry.partition + '.img') -or
        [string]$entry.bytes -cnotmatch '^[1-9][0-9]*$' -or
        [string]$entry.sha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'Invalid partition entry.' }
}
if ($review.revision -ne $Revision -or $review.baseline_revision -ne ($Revision - 1) -or $previous.revision -ne ($Revision - 1)) {
    throw 'Wrong revision.'
}
if ($Revision -ge 64 -and $review.reflected_platform_check_retained -cne $true) {
    throw 'The optimized APK has no verified reflected platform check.'
}
Assert-File $previousPath $null $review.baseline_manifest_sha256
foreach ($field in @('original_systemui_unchanged','complete_avb_chain_verified',
    'all_filesystem_stages_verified','normal_module_build_passed','installed_qti_retained',
    'fingerprint_control_label_corrected','pen_settings_preinstalled','settings_entry_present',
    'v1_signature_verified','platform_certificate_verified','api1_bootstrap_compile_passed')) {
    if ($review.$field -cne $true) { throw "Missing verification: $field" }
}
if ($review.qti_source_service_integrated -cne $false -or $review.face_candidate_installed -cne $false -or
    $review.launcher_entry_present -cne $false -or $review.recovery_revision_retained -ne 59 -or
    $review.dex_version -cne '035' -or $review.settings_category -cne 'com.android.settings.category.ia.connect' -or
    $review.min_sdk_version -ne 1 -or $review.target_sdk_version -ne 37) {
    throw 'Unexpected service, entry point or Recovery change.'
}
Assert-Set @($review.files.partition) @('system_ext','vbmeta_system') 'flashed partitions'
Assert-Set @($review.entries.PSObject.Properties.Name) @('system_ext') 'filesystem scope'
Assert-Set @($review.entries.system_ext.PSObject.Properties.Name) @($app) 'application scope'
if ($review.entries.system_ext.$app.sha256 -cne $review.apk_sha256 -or
    $review.apk_sha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'APK identity differs from build receipt.' }
$stage = $review.partition_reports.system_ext
Assert-Set @($stage.changed_files) @($app) 'changed files'
if ($Revision -eq 63) {
    Assert-Set @($stage.created_nodes) @('app/ShengPenSettings',$app) 'new nodes'
    Assert-Set @($stage.replaced_files) @() 'replaced files'
} else {
    Assert-Set @($stage.created_nodes) @() 'new nodes'
    Assert-Set @($stage.replaced_files) @($app) 'replaced files'
    Assert-Set @($stage.explicit_apk_mtime_updates.PSObject.Properties.Name) @($app) 'APK timestamp updates'
    if ($stage.explicit_apk_mtime_updates.$app -le 0) { throw 'Invalid APK timestamp.' }
}
if ($stage.metadata_preserved -cne $true) {
    throw 'Unexpected filesystem metadata or replacement.'
}
if ($review.boot_policy.actual_partition_neverallows_passed -cne $true -or
    $review.boot_policy.actual_partition_combination_compiled -cne $true -or
    $review.boot_policy.split_policy_selected_by_partition_hashes -cne $true) {
    throw 'Actual boot policy not validated.'
}
$baseline = @($previous.files) + @($previous.unchanged_partition_files) + @($previous.unchanged_boot_dependencies)
foreach ($entry in $baseline) {
    if ($null -eq $entry.name) { $entry | Add-Member NoteProperty name ($entry.partition + '.img') }
    Assert-Entry $entry
}
Assert-Set @($baseline.partition) $allowed 'sealed baseline'
Assert-Set @($review.baseline_partitions.partition) $allowed 'candidate baseline'
foreach ($entry in $review.baseline_partitions) {
    Assert-Entry $entry
    $sealed = @($baseline | Where-Object partition -CEQ $entry.partition)
    if ($sealed.Count -ne 1 -or $sealed[0].bytes -ne $entry.bytes -or $sealed[0].sha256 -cne $entry.sha256) {
        throw 'Candidate baseline differs from the sealed preceding revision.'
    }
}
Assert-Set @($review.unchanged_partition_files.partition) @($allowed | Where-Object {
    $_ -cnotin @('system_ext','vbmeta_system') }) 'retained partitions'
foreach ($entry in $review.unchanged_partition_files) {
    Assert-Entry $entry
    $sealed = @($baseline | Where-Object partition -CEQ $entry.partition)
    if ($sealed[0].bytes -ne $entry.bytes -or $sealed[0].sha256 -cne $entry.sha256) {
        throw 'Retained dependency changed.'
    }
}
$sources = @($review.sources_sha256.PSObject.Properties)
if ($sources.Count -eq 0) { throw 'No verified app sources.' }
foreach ($source in $sources) {
    if ($source.Name -cnotmatch '^device/xiaomi/sheng/interfaces/input/pen/[A-Za-z0-9_./-]+$' -or
        $source.Name -match '(^|/)\.\.(/|$)') { throw 'Unexpected source path.' }
    Assert-File (Join-Path $workspace $source.Name) $null $source.Value
}
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
    $command = if ($part -cin $logical) { "sha256sum /dev/block/mapper/${part}_a" }
        else { 'head -c ' + [long]$entry.bytes + ' /dev/block/by-name/' + $part + '_a | sha256sum' }
    if (((Invoke-Target $adb @('shell',$command)).Trim() -split '\s+')[0] -cne $entry.sha256) {
        throw "Live baseline mismatch: $part"
    }
}
Write-Output "r$Revision package, application scope and all 14 installed baseline partitions verified."
if (-not $Flash) { return }
if ($Revision -ge 64) {
    # PackageCacher stats the app directory; preserving that inode can retain
    # its old parsed manifest. Expire only this app's regenerable parse cache.
    $penCaches = (Invoke-Target $adb @('shell',
        'find /data/system/package_cache -mindepth 2 -maxdepth 2 -type f -name "ShengPenSettings-*" -print')).Trim()
    if ($penCaches) {
        foreach ($penCache in ($penCaches -split '\r?\n')) {
            if ($penCache -cnotmatch '^/data/system/package_cache/[0-9a-f]{40}/ShengPenSettings-[0-9]+--?[0-9]+$') {
                throw 'Unexpected pen parse-cache path.'
            }
            Invoke-Target $adb @('shell','rm','-f','--',$penCache) | Out-Null
        }
    }
}
Invoke-Target $adb @('reboot','fastboot') | Write-Output
Wait-Fastboot $true
Invoke-Target $fastboot @('flash','system_ext_a',$images['system_ext']) | Write-Output
Invoke-Target $fastboot @('reboot','bootloader') | Write-Output
Wait-Fastboot $false
if ((Invoke-Target $fastboot @('getvar','unlocked')) -cnotmatch '(?m)^unlocked:\s*yes\s*$') {
    throw 'Locked bootloader.'
}
Invoke-Target $fastboot @('flash','vbmeta_system_a',$images['vbmeta_system']) | Write-Output
Invoke-Target $fastboot @('reboot') | Write-Output
Write-Output "r$Revision system_ext and vbmeta_system written to A; postboot verification is required."
