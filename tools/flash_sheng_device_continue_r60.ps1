param([switch]$Flash, [ValidateSet(60,61)][int]$Revision = 60)
# Default mode verifies the package and live baseline. Only -Flash permits writes.
# Requires PowerShell 7 for ProcessStartInfo.ArgumentList.
$ErrorActionPreference = 'Stop'
$workspace = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$batch = Join-Path $workspace "artifacts/system-hardware-followup-sheng-r$Revision"

function Assert-Set([object[]]$actual, [string[]]$expected, [string]$label) {
    $values = @($actual | ForEach-Object { [string]$_ })
    if ($values.Count -ne $expected.Count -or
        (($values | Sort-Object) -join "`n") -cne (($expected | Sort-Object) -join "`n")) {
        throw "Unexpected $label."
    }
}
function Assert-Hash([object]$digest, [string]$label) {
    if ([string]$digest -cnotmatch '^[0-9a-f]{64}$') { throw "Invalid SHA256: $label" }
}
function Assert-Entry([object]$entry) {
    if ($null -eq $entry -or [string]$entry.partition -cnotmatch '^[a-z_]+$' -or
        [string]$entry.name -cne ([string]$entry.partition + '.img') -or
        [string]$entry.bytes -cnotmatch '^[1-9][0-9]*$') { throw 'Invalid partition receipt.' }
    Assert-Hash $entry.sha256 $entry.partition
}
function Assert-File([string]$path, [object]$bytes, [string]$digest) {
    Assert-Hash $digest $path
    $file = Get-Item -LiteralPath $path
    if ($file.PSIsContainer -or ($null -ne $bytes -and $file.Length -ne [long]$bytes) -or
        (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $digest) {
        throw "File changed: $path"
    }
}
function Workspace-Path([string]$relative, [string]$root) {
    if ($relative -cmatch '(^|/)\.\.?(/|$)' -or $relative.Contains('\') -or
        $relative.Contains(':') -or $relative.StartsWith('/')) { throw 'Invalid workspace-relative path.' }
    $path = [IO.Path]::GetFullPath((Join-Path $root $relative))
    if (-not $path.StartsWith($root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Path leaves workspace.'
    }
    return $path
}
function Assert-R60Manifest([object]$review, [object]$previous, [object]$recovery, [string]$root) {
    if ($review.revision -ne $Revision -or $review.baseline_revision -ne 53 -or $previous.revision -ne 53) {
        throw "Expected r$Revision over Android r53."
    }
    foreach ($flag in @('complete_avb_chain_verified','all_filesystem_stages_verified',
        'original_systemui_unchanged','normal_module_build_passed','vintf_unchanged',
        'nonexistent_tap_sensors_removed',
        'precise_wakeup_labels_integrated','no_new_allow_rules','touch_r50_retained',
        'dolby_ui_r51_retained','dolby_media_r52_retained','keyboard_r53_retained')) {
        if ($review.$flag -cne $true) { throw "Missing successful r60 guard: $flag" }
    }
    if ($previous.complete_avb_chain_verified -cne $true -or
        $previous.original_systemui_unchanged -cne $true -or
        $review.full_product_build_passed -cne $false -or $review.hardware_boot_tested -cne $false -or
        $review.pen_fixed -cne $false -or $review.face_candidate_installed -cne $false -or
        $review.recovery_revision_retained -ne 59 -or $recovery.revision -ne 59 -or
        $recovery.avb_verified -cne $true) { throw 'Invalid baseline, scope or validation claims.' }
    if ($review.boot_policy.actual_partition_combination_compiled -cne $true -or
        $review.boot_policy.actual_partition_neverallows_passed -cne $true -or
        $review.boot_policy.split_policy_selected_by_partition_hashes -cne $true) {
        throw 'Actual partition split-policy/neverallow validation missing.'
    }
    Assert-Set @($review.files.partition) @('odm','vendor','vbmeta') 'r60 flash partitions'
    Assert-Set @($review.unchanged_partition_files.partition) @('product','system_ext','vbmeta_system') 'unchanged partitions'
    Assert-Set @($review.baseline_sha256.PSObject.Properties.Name) @('odm','product','system_ext','vendor','vbmeta','vbmeta_system') 'baseline hashes'
    $baseline = @($previous.files) + @($previous.unchanged_partition_files)
    Assert-Set @($baseline.partition) @('odm','product','system_ext','vendor','vbmeta','vbmeta_system') 'r53 baseline receipts'
    foreach ($entry in $baseline) {
        Assert-Entry $entry
        if ($review.baseline_sha256.($entry.partition) -cne $entry.sha256) { throw "r53 baseline mismatch: $($entry.partition)" }
    }
    foreach ($entry in @($review.files) + @($review.unchanged_partition_files)) { Assert-Entry $entry }
    foreach ($entry in $review.unchanged_partition_files) {
        $old = @($baseline | Where-Object partition -CEQ $entry.partition)[0]
        if ($entry.sha256 -cne $old.sha256 -or $entry.bytes -ne $old.bytes) { throw 'Unchanged partition altered.' }
    }
    $oldDependencies = @($previous.unchanged_boot_dependencies)
    if ($oldDependencies.Count -eq 0 -or @($oldDependencies | Where-Object partition -CEQ 'boot').Count -ne 1 -or
        @($oldDependencies | Where-Object partition -CEQ 'recovery').Count -ne 1) { throw 'Missing baseline boot/recovery dependency.' }
    # The packager additionally seals the original system image used in the
    # actual split-policy check. Bind it to the existing accepted r38 receipt.
    if (@($oldDependencies | Where-Object partition -CEQ 'system').Count -ne 0) { throw 'Unexpected inherited system dependency.' }
    $restore = Get-Content -LiteralPath (Join-Path $root 'reports/device/r38-restore-20261110/restore-manifest.json') -Raw | ConvertFrom-Json
    $systemReceipt = @($restore.files | Where-Object partition -CEQ 'system')
    if ($systemReceipt.Count -ne 1) { throw 'Missing accepted system receipt.' }
    Assert-Hash $systemReceipt[0].sha256 'accepted system image'
    $oldDependencies += $systemReceipt[0]
    Assert-Set @($review.unchanged_boot_dependencies.partition) @($oldDependencies.partition) 'boot dependencies'
    foreach ($entry in $review.unchanged_boot_dependencies) {
        if ([string]$entry.partition -cnotmatch '^[a-z_]+$' -or [string]$entry.bytes -cnotmatch '^[1-9][0-9]*$') {
            throw 'Invalid boot dependency.'
        }
        Assert-Hash $entry.sha256 $entry.partition
        $old = @($oldDependencies | Where-Object partition -CEQ $entry.partition)
        if ($old.Count -ne 1) { throw 'Duplicated boot dependency.' }
        $expected = if ($entry.partition -ceq 'recovery') { $recovery } else { $old[0] }
        if ($entry.bytes -ne $expected.bytes -or $entry.sha256 -cne $expected.sha256) {
            throw "Boot dependency changed: $($entry.partition)"
        }
    }
    Assert-Set @($review.entries.PSObject.Properties.Name) @('vendor','odm') 'entry partitions'
    Assert-Set @($review.partition_reports.PSObject.Properties.Name) @('vendor','odm') 'filesystem reports'
    $scopes = @{
        vendor = @('build.prop','etc/init/init.sm8550.rc','etc/selinux/vendor_sepolicy.cil')
        odm = @('overlay/FrameworkResOverlaySheng.apk')
    }
    if ($Revision -eq 60) {
        if ($review.qti_source_service_integrated -cne $true) { throw 'QTI service integration missing.' }
        $scopes.vendor += 'bin/hw/vendor.qti.media.c2@1.0-service'
    } elseif ($review.qti_source_service_integrated -cne $false -or
        $review.installed_qti_retained -cne $true -or $null -ne $review.factory_probe) {
        throw 'r61 must retain the installed QTI service and exclude the failed candidate.'
    }
    foreach ($partition in @('vendor','odm')) {
        Assert-Set @($review.entries.$partition.PSObject.Properties.Name) $scopes[$partition] "$partition file scope"
        Assert-Set @($review.partition_reports.$partition.changed_files) $scopes[$partition] "$partition filesystem delta"
        if ($review.partition_reports.$partition.metadata_preserved -cne $true) { throw 'Filesystem metadata not preserved.' }
        foreach ($property in $review.entries.$partition.PSObject.Properties) {
            if ($property.Value.kind -cne 'file' -or [string]$property.Value.bytes -cnotmatch '^[1-9][0-9]*$') {
                throw 'Invalid installed-file receipt.'
            }
            Assert-Hash $property.Value.sha256 $property.Name
        }
    }
    $tapKeys = @('ro.vendor.sensors.xiaomi.single_tap','ro.vendor.sensors.xiaomi.double_tap')
    $changes = @($review.changed_properties)
    if ($changes -ccontains 'ro.vendor.build.uuid') { $changes = @($changes | Where-Object { $_ -cne 'ro.vendor.build.uuid' }) }
    Assert-Set $changes $tapKeys 'property delta'
    Assert-Set @($review.changed_overlay_resources) @('config_dozeTapSensorType','config_dozeDoubleTapSensorType') 'overlay delta'
    $wakeupPaths = @('/devices/platform/soc/soc:xm_battmngr/wakeup',
        '/devices/platform/soc/soc:fingerprint_fpc/wakeup','/devices/platform/soc/soc:xiaomi_wifi_gpio/wakeup',
        '/devices/platform/soc/8c0000.qcom,qupv3_2_geni_se/884000.i2c/i2c-5/5-004c/wakeup')
    if (@($review.policy_added).Count -ne 4) { throw 'Unexpected policy delta.' }
    foreach ($path in $wakeupPaths) {
        $lines = @($review.policy_added | Where-Object { $_ -cmatch ('^\(genfscon sysfs .*' + [regex]::Escape($path) + '.*sysfs_wakeup') })
        if ($lines.Count -ne 1) { throw "Missing precise wakeup label: $path" }
    }
    foreach ($property in $review.boot_policy.input_sha256.PSObject.Properties) { Assert-Hash $property.Value $property.Name }
    $policyHashes = @($review.boot_policy.input_sha256.PSObject.Properties | Where-Object { $_.Name.EndsWith('/vendor_sepolicy.cil') })
    if ($policyHashes.Count -ne 1 -or $policyHashes[0].Value -cne $review.entries.vendor.'etc/selinux/vendor_sepolicy.cil'.sha256) {
        throw 'Policy validation did not use the packaged vendor policy.'
    }
    if ($Revision -eq 60) {
      $factory = $review.factory_probe
      if ($factory.returncode -ne 0 -or $factory.registered_service -cne $false -or
        $factory.serial -cne 'ca10ede3' -or $factory.listed_components -le 0 -or
        $factory.seccomp_enabled -cne $true -or $factory.process_teardown_passed -cne $true -or
        $factory.service_sha256 -cne $review.entries.vendor.'bin/hw/vendor.qti.media.c2@1.0-service'.sha256) {
        throw 'Missing matching isolated QTI factory probe.'
      }
    } else {
        Assert-Hash $review.retained_qti_sha256 'retained QTI service'
    }
    foreach ($field in @('build_log_sha256','source_mirror_sha256','post_audit_sha256')) { Assert-Hash $review.$field $field }
    Assert-Set @($review.packaging_inputs_sha256.PSObject.Properties.Name) @('@sepolicy_file_contexts',
        'obj/PACKAGING/vendor_intermediates/vendor_image_info.txt',
        'obj/PACKAGING/odm_intermediates/odm_image_info.txt') 'frozen EROFS packaging inputs'
    foreach ($property in $review.packaging_inputs_sha256.PSObject.Properties) { Assert-Hash $property.Value $property.Name }
    $requiredSources = @('BoardConfig.mk','device.mk','interfaces/compat/codec2/Android.bp',
        'interfaces/compat/codec2/qti_service.cpp','properties/vendor.prop','rootdir/etc/init.sm8550.rc',
        'overlay/FrameworkResOverlaySheng/res/values/config.xml',
        'overlay/FrameworkResOverlaySheng/res/values/platform-defaults.xml','sepolicy/vendor/genfs_contexts')
    foreach ($relative in $requiredSources) {
        if ($null -eq $review.sources_sha256.PSObject.Properties['device/xiaomi/sheng/' + $relative]) {
            throw "Missing source digest: $relative"
        }
    }
    foreach ($property in $review.sources_sha256.PSObject.Properties) {
        if (-not $property.Name.StartsWith('device/xiaomi/sheng/', [StringComparison]::Ordinal)) { throw 'Source scope leaves device tree.' }
        Assert-File (Workspace-Path $property.Name $root) $null $property.Value
    }
    Assert-File (Join-Path $root 'device/xiaomi/sheng/tools/postprocess_vendor.py') $null $review.generated_vendor_postprocessor_sha256
    return $baseline
}

if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'Run this script with PowerShell 7 (pwsh).' }
$review = Get-Content -LiteralPath (Join-Path $batch 'build-result.json') -Raw | ConvertFrom-Json
$previous = Get-Content -LiteralPath (Join-Path $workspace 'artifacts/system-hardware-followup-sheng-r53/build-result.json') -Raw | ConvertFrom-Json
$recovery = Get-Content -LiteralPath (Join-Path $workspace 'reports/device/20261112-recovery-pen/r59-package.json') -Raw | ConvertFrom-Json
$baseline = @(Assert-R60Manifest $review $previous $recovery $workspace)
$images = @{}
foreach ($entry in $review.files) {
    $path = Join-Path $batch $entry.name
    Assert-File $path $entry.bytes $entry.sha256
    $images[$entry.partition] = $path
}
$evidence = Join-Path $workspace 'reports/device/20261112-device-continue'
New-Item -ItemType Directory -Force $evidence | Out-Null
$adb = Join-Path $workspace 'tools/platform-tools/adb.exe'
$fastboot = Join-Path $workspace 'tools/platform-tools/fastboot.exe'
$log = Join-Path $evidence ("flash-r$Revision-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-operations.txt')
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
    if (-not $process.Start()) { throw 'Device tool failed to start.' }
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
    if ((Invoke-Target $fastboot @('getvar','product')) -cnotmatch '(?m)^product:\s*sheng\s*$' -or
        (Invoke-Target $fastboot @('getvar','current-slot')) -cnotmatch '(?m)^current-slot:\s*a\s*$') { throw 'Fastboot target/slot mismatch.' }
    $expected = if ($userspace) { 'yes' } else { 'no' }
    if ((Invoke-Target $fastboot @('getvar','is-userspace')) -cnotmatch ('(?m)^is-userspace:\s*' + $expected + '\s*$')) {
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
if ((Invoke-Target $adb @('shell','getprop','ro.build.fingerprint')).Trim() -cne
    'Xiaomi/lineage_sheng/sheng:17/CP2A.260605.016/eng.root:userdebug/test-keys' -or
    (Invoke-Target $adb @('shell','getprop','ro.boot.slot_suffix')).Trim() -cne '_a' -or
    (Invoke-Target $adb @('shell','getprop','sys.boot_completed')).Trim() -cne '1' -or
    (Invoke-Target $adb @('shell','getprop','ro.boot.flash.locked')).Trim() -cne '0' -or
    (Invoke-Target $adb @('shell','id','-u')).Trim() -cne '0' -or
    (Invoke-Target $adb @('shell','getenforce')).Trim() -cne 'Enforcing') {
    throw 'Expected rooted, unlocked, boot-complete LineageOS/Android 17 A-slot tablet in Enforcing.'
}
foreach ($entry in $baseline + @($review.unchanged_boot_dependencies)) {
    $partition = [string]$entry.partition
    $arguments = if ($partition -cin @('system','odm','product','system_ext','vendor','vendor_dlkm','system_dlkm')) {
        @('shell','sha256sum',('/dev/block/mapper/' + $partition + '_a'))
    } else {
        # Partition and decimal byte count are validated above; no manifest shell text is executed.
        @('shell',('head -c ' + [long]$entry.bytes + ' /dev/block/by-name/' + $partition + '_a | sha256sum'))
    }
    $digest = ((Invoke-Target $adb $arguments).Trim() -split '\s+')[0]
    if ($digest -cne $entry.sha256) { throw "Unexpected installed baseline/dependency: $partition" }
}
$uiDigest = ((Invoke-Target $adb @('shell','sha256sum','/system_ext/priv-app/SystemUI/SystemUI.apk')).Trim() -split '\s+')[0]
if ($uiDigest -cne '33017b0d59e28da5db3e089a98f49601de508228a012392ee2d04c82cda3ccb1') { throw 'Original SystemUI changed.' }
if ($Revision -eq 61) {
    $qtiDigest = ((Invoke-Target $adb @('shell','sha256sum','/vendor/bin/hw/vendor.qti.media.c2@1.0-service')).Trim() -split '\s+')[0]
    if ($qtiDigest -cne $review.retained_qti_sha256) { throw 'Retained QTI service differs from installed baseline.' }
}
Write-Output "r$Revision package and ca10ede3 A-slot Android r53/Recovery r59 baseline verified; runtime remains pending."
if (-not $Flash) { return }
Invoke-Target $adb @('reboot','fastboot') | Write-Output
Wait-Fastboot $true
foreach ($partition in @('odm','vendor')) {
    Invoke-Target $fastboot @('flash',($partition + '_a'),$images[$partition]) | Write-Output
}
Invoke-Target $fastboot @('reboot','bootloader') | Write-Output
Wait-Fastboot $false
if ((Invoke-Target $fastboot @('getvar','unlocked')) -cnotmatch '(?m)^unlocked:\s*yes\s*$') { throw 'Locked bootloader.' }
Invoke-Target $fastboot @('flash','vbmeta_a',$images['vbmeta']) | Write-Output
Invoke-Target $fastboot @('reboot') | Write-Output
Write-Output "Three verified r$Revision images written to A. Partition readback, Enforcing and hardware/runtime validation remain required."
