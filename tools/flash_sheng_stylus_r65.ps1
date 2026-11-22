# SPDX-License-Identifier: Apache-2.0
param([switch]$Flash)
# Verify the sealed candidate and all fourteen live r64 partitions by default.
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7 is required.' }
$taskWorkspace = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$taskBatch = Join-Path $taskWorkspace 'artifacts/system-hardware-followup-sheng-r65'
$taskBaselinePath = Join-Path $taskWorkspace 'artifacts/system-hardware-followup-sheng-r64/build-result.json'
$taskEvidence = Join-Path $taskWorkspace ('reports/device/20261114-stylus-service/flash-r65-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff'))
$null = New-Item -ItemType Directory -Path $taskEvidence
$taskLog = Join-Path $taskEvidence 'device.log'
$taskAdb = Join-Path $taskWorkspace 'tools/platform-tools/adb.exe'
$taskFastboot = Join-Path $taskWorkspace 'tools/platform-tools/fastboot.exe'
$taskAllowed = @('system','system_ext','product','vendor','odm','vendor_dlkm','system_dlkm',
    'init_boot','boot','dtbo','recovery','vendor_boot','vbmeta','vbmeta_system')
$taskLogical = @('system','system_ext','product','vendor','odm','vendor_dlkm','system_dlkm')
$taskUpdated = @('system','system_ext','product','vendor','vbmeta_system','vbmeta')
$taskReceipt = [ordered]@{
    started_utc = [DateTime]::UtcNow.ToString('o')
    serial = 'ca10ede3'
    slot = 'a'
    revision = 65
    baseline_revision = 64
    package_verified = $false
    live_baseline_verified = $false
    flashed_partitions = @()
    postboot_partitions_verified = @()
    debug_root_restore_requested = $false
    completed = $false
    hardware_writing_tested = $false
}

function Assert-File([string]$Path, [object]$Bytes, [string]$Digest) {
    if ($Digest -cnotmatch '^[0-9a-f]{64}$') { throw "Invalid file hash: $Path" }
    $taskItem = Get-Item -LiteralPath $Path
    if ($taskItem.PSIsContainer -or ($null -ne $Bytes -and $taskItem.Length -ne [long]$Bytes) -or
        (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Digest) {
        throw "Changed file: $Path"
    }
}
function Assert-Set([object[]]$Actual, [string[]]$Expected, [string]$Label) {
    if ($Actual.Count -ne $Expected.Count -or
        (($Actual | Sort-Object) -join ',') -cne (($Expected | Sort-Object) -join ',')) {
        throw "Unexpected $Label"
    }
}
function Assert-Entry([object]$Entry) {
    if ([string]$Entry.partition -cnotin $taskAllowed -or
        [string]$Entry.name -cne ([string]$Entry.partition + '.img') -or
        [string]$Entry.bytes -cnotmatch '^[1-9][0-9]*$' -or
        [string]$Entry.sha256 -cnotmatch '^[0-9a-f]{64}$') { throw 'Invalid partition entry.' }
}
function Invoke-Target([string]$Tool, [string[]]$Arguments) {
    $taskStart = [Diagnostics.ProcessStartInfo]::new()
    $taskStart.FileName = $Tool
    $taskStart.WorkingDirectory = $taskWorkspace
    $taskStart.UseShellExecute = $false
    $taskStart.CreateNoWindow = $true
    $taskStart.RedirectStandardOutput = $true
    $taskStart.RedirectStandardError = $true
    foreach ($taskArgument in (@('-s','ca10ede3') + $Arguments)) { $taskStart.ArgumentList.Add($taskArgument) }
    Add-Content -LiteralPath $taskLog ((Get-Date -Format o) + ' ' + [IO.Path]::GetFileName($Tool) + ' ' + ($Arguments | ConvertTo-Json -Compress))
    $taskProcess = [Diagnostics.Process]::new()
    $taskProcess.StartInfo = $taskStart
    try {
        if (-not $taskProcess.Start()) { throw 'Device tool failed to start.' }
        $taskStdout = $taskProcess.StandardOutput.ReadToEndAsync()
        $taskStderr = $taskProcess.StandardError.ReadToEndAsync()
        $taskTimeout = if ($Arguments[0] -ceq 'flash') { 300000 } elseif ($Arguments[0] -ceq 'shell') { 60000 } else { 20000 }
        if (-not $taskProcess.WaitForExit($taskTimeout)) {
            $taskProcess.Kill()
            $taskProcess.WaitForExit()
            throw 'Device tool timed out.'
        }
        $taskOutput = $taskStdout.Result + "`n" + $taskStderr.Result
        Add-Content -LiteralPath $taskLog $taskOutput
        if ($taskProcess.ExitCode -ne 0) { throw $taskOutput }
        return $taskOutput
    } finally { $taskProcess.Dispose() }
}
function Assert-Android([switch]$RestoreDebugRoot) {
    foreach ($taskCheck in @(@('ro.product.device','sheng'),@('ro.boot.slot_suffix','_a'),
        @('sys.boot_completed','1'),@('ro.boot.flash.locked','0'))) {
        if ((Invoke-Target $taskAdb @('shell','getprop',$taskCheck[0])).Trim() -cne $taskCheck[1]) {
            throw 'Unexpected live device or boot state.'
        }
    }
    $taskShellUid = (Invoke-Target $taskAdb @('shell','id','-u')).Trim()
    if ($RestoreDebugRoot -and $taskShellUid -ceq '2000' -and
        -not $taskReceipt.debug_root_restore_requested) {
        # A real reboot resets adbd even when the preflash endpoint was rooted.
        # Device, slot, boot completion and unlocked state were checked above.
        $taskReceipt.debug_root_restore_requested = $true
        Invoke-Target $taskAdb @('root') | Write-Output
        throw 'Waiting for adbd to reconnect after restoring debug root.'
    }
    if ($taskShellUid -cne '0' -or
        (Invoke-Target $taskAdb @('shell','getenforce')).Trim() -cne 'Enforcing') {
        throw 'The rooted Enforcing endpoint is required.'
    }
}
function Assert-LivePartition([object]$Entry) {
    Assert-Entry $Entry
    $taskPart = [string]$Entry.partition
    $taskCommand = if ($taskPart -cin $taskLogical) { "sha256sum /dev/block/mapper/${taskPart}_a" }
        else { 'head -c ' + [long]$Entry.bytes + ' /dev/block/by-name/' + $taskPart + '_a | sha256sum' }
    if (((Invoke-Target $taskAdb @('shell',$taskCommand)).Trim() -split '\s+')[0] -cne $Entry.sha256) {
        throw "Live partition mismatch: $taskPart"
    }
}
function Assert-Fastboot([bool]$Userspace) {
    $taskExpected = if ($Userspace) { 'yes' } else { 'no' }
    if ((Invoke-Target $taskFastboot @('getvar','product')) -cnotmatch '(?m)^product:\s*sheng\s*$' -or
        (Invoke-Target $taskFastboot @('getvar','current-slot')) -cnotmatch '(?m)^current-slot:\s*a\s*$' -or
        (Invoke-Target $taskFastboot @('getvar','is-userspace')) -cnotmatch ('(?m)^is-userspace:\s*' + $taskExpected + '\s*$')) {
        throw 'Wrong fastboot device, slot or mode.'
    }
}
function Wait-Fastboot([bool]$Userspace) {
    $taskDeadline = [DateTime]::UtcNow.AddSeconds(120)
    do {
        Start-Sleep -Seconds 3
        try { Assert-Fastboot $Userspace; return } catch { $taskFailure = $_ }
    } while ([DateTime]::UtcNow -lt $taskDeadline)
    throw $taskFailure
}

try {
    $taskManifestPath = Join-Path $taskBatch 'build-result.json'
    $taskReview = Get-Content -LiteralPath $taskManifestPath -Raw | ConvertFrom-Json
    $taskPrevious = Get-Content -LiteralPath $taskBaselinePath -Raw | ConvertFrom-Json
    if ($taskReview.revision -ne 65 -or $taskReview.baseline_revision -ne 64 -or $taskPrevious.revision -ne 64) {
        throw 'Wrong revision.'
    }
    Assert-File $taskBaselinePath $null $taskReview.baseline_manifest_sha256
    foreach ($taskField in @('original_systemui_unchanged','complete_avb_chain_verified',
        'all_filesystem_stages_verified','qualified_module_build_passed','installed_qti_retained',
        'fingerprint_control_label_corrected','keyboard_r53_retained','pen_settings_preinstalled',
        'pen_permanent_service_preinstalled','runtime_inputs_verified')) {
        if ($taskReview.$taskField -cne $true) { throw "Missing verification: $taskField" }
    }
    if ($taskReview.frozen_api_version -ne 1 -or $taskReview.frozen_api_hash -cnotmatch '^[0-9a-f]{40}$' -or
        $taskReview.recovery_revision_retained -ne 59 -or $taskReview.face_candidate_installed -cne $false) {
        throw 'Unexpected API, face candidate or Recovery change.'
    }
    if ($taskReview.guard_receipt -cnotmatch '^reports/device/20261114-stylus-service/(normal-module-build-[a-z0-9_]+/guard-status|targeted-module-build-[a-z0-9_]+/build-receipt)\.json$' -or
        $taskReview.stylus_artifact_receipt -cnotmatch '^reports/device/20261114-stylus-service/[A-Za-z0-9_-]+/receipt\.json$') {
        throw 'Unexpected qualification receipt path.'
    }
    $taskGuardPath = Join-Path $taskWorkspace $taskReview.guard_receipt
    $taskArtifactsPath = Join-Path $taskWorkspace $taskReview.stylus_artifact_receipt
    Assert-File $taskGuardPath $null $taskReview.guard_sha256
    Assert-File $taskArtifactsPath $null $taskReview.stylus_artifacts_sha256
    $taskGuard = Get-Content -LiteralPath $taskGuardPath -Raw | ConvertFrom-Json
    $taskArtifacts = Get-Content -LiteralPath $taskArtifactsPath -Raw | ConvertFrom-Json
    $taskTargeted = $taskGuard.kind -ceq 'targeted-stylus-link-and-apk'
    $taskBuildPassed = if ($taskTargeted) {
        $taskGuard.passed -ceq $true -and $taskGuard.targeted_modules_linked -ceq $true -and
        $taskGuard.normal_module_build_passed -ceq $false -and $taskGuard.ninja_graph_loaded -ceq $false -and
        $taskArtifacts.targeted_module_build_passed -ceq $true -and $taskReview.targeted_module_build_passed -ceq $true
    } else { $taskGuard.exit_code -eq 0 -and $taskGuard.normal_module_build_passed -ceq $true }
    if (-not $taskBuildPassed -or $taskArtifacts.qualified_module_build_passed -cne $true -or
        $taskGuard.compiler_restored -cne $true -or $taskArtifacts.passed -cne $true -or
        $taskArtifacts.api_frozen -cne $true -or $taskArtifacts.guard_sha256 -cne $taskReview.guard_sha256 -or
        $taskArtifacts.frozen_api_hash -cne $taskReview.frozen_api_hash) { throw 'Frozen stylus module build is not qualified.' }
    $taskSwap = $taskGuard.swap_policy
    if ($taskTargeted) {
        $taskSwapPath = Join-Path (Split-Path $taskGuardPath) 'swap-priority.json'
        Assert-File $taskSwapPath $null $taskArtifacts.swap_receipt_sha256
        $taskSwap = Get-Content -LiteralPath $taskSwapPath -Raw | ConvertFrom-Json
    }
    if ($taskSwap.complete -cne $true -or $taskSwap.policy -cne 'C-only' -or
        $taskSwap.e_drive_swap_allowed -cne $false -or
        $taskReview.build_swap_policy -cne 'C-only' -or $taskReview.e_drive_swap_allowed -cne $false -or
        $taskReview.native_c_staging -cne $true) { throw 'C-only build swap and native staging qualification are required.' }
    Assert-Set @($taskReview.files.partition) $taskUpdated 'updated partitions'
    Assert-Set @($taskReview.entries.PSObject.Properties.Name) @('system','system_ext','product','vendor') 'filesystem partitions'
    $taskRequired = @{
        system = @('etc/vintf/compatibility_matrix.device.xml')
        system_ext = @('priv-app/ShengStylus/ShengStylus.apk','etc/permissions/privapp-permissions-org.lineageos.sheng.stylus.xml')
        vendor = @('bin/hw/vendor.lineage.sheng.stylus-service','lib64/vendor.lineage.sheng.stylus-V1-ndk.so',
            'etc/init/vendor.lineage.sheng.stylus-service.rc','etc/vintf/manifest/vendor.lineage.sheng.stylus-service.xml')
        product = @()
    }
    foreach ($taskPart in $taskRequired.Keys) {
        $taskNames = @($taskReview.entries.$taskPart.PSObject.Properties.Name)
        foreach ($taskName in $taskRequired[$taskPart]) {
            if ($taskName -cnotin $taskNames) { throw "Missing installed file: $taskPart/$taskName" }
        }
        foreach ($taskName in $taskNames) {
            if ($taskName -cnotin $taskRequired[$taskPart] -and
                ($taskPart -ceq 'system' -or $taskName -cnotmatch '^etc/selinux/[A-Za-z0-9_./-]+$' -or
                 $taskName -match '(^|/)\.\.(/|$)')) { throw 'Unexpected filesystem file scope.' }
        }
        if ($taskReview.partition_reports.$taskPart.metadata_preserved -cne $true) { throw 'Filesystem metadata verification is missing.' }
    }
    if ($taskReview.entries.system_ext.'priv-app/ShengStylus/ShengStylus.apk'.sha256 -cne $taskArtifacts.apk_sha256 -or
        $taskReview.entries.vendor.'bin/hw/vendor.lineage.sheng.stylus-service'.sha256 -cne $taskArtifacts.service_sha256 -or
        $taskReview.native_dependency_providers.'vendor.lineage.sheng.stylus-V1-ndk.so'.sha256 -cne
            $taskArtifacts.dependency_sha256.'vendor.lineage.sheng.stylus-V1-ndk.so') { throw 'Stylus artifact identity mismatch.' }
    foreach ($taskField in @('actual_partition_neverallows_passed','actual_partition_combination_compiled','split_policy_selected_by_partition_hashes')) {
        if ($taskReview.boot_policy.$taskField -cne $true) { throw 'Actual boot policy is not qualified.' }
    }
    if ($taskReview.vintf.actual_partition_combination_compatible -cne $true) { throw 'Actual VINTF combination is not qualified.' }
    $taskSources = @($taskReview.sources_sha256.PSObject.Properties)
    if ($taskSources.Count -eq 0) { throw 'Source qualification is missing.' }
    foreach ($taskSource in $taskSources) {
        if ($taskSource.Name -cne 'configs/vintf/framework_stylus_matrix.xml' -and
            ($taskSource.Name -cnotmatch '^interfaces/input/stylus/[A-Za-z0-9_./-]+$' -or
             $taskSource.Name -match '(^|/)\.\.(/|$)')) { throw 'Unexpected source path.' }
        Assert-File (Join-Path $taskWorkspace ('device/xiaomi/sheng/' + $taskSource.Name)) $null $taskSource.Value
    }
    $taskBaseline = @($taskPrevious.files) + @($taskPrevious.unchanged_partition_files) + @($taskPrevious.unchanged_boot_dependencies)
    foreach ($taskEntry in $taskBaseline) {
        if ($null -eq $taskEntry.name) { $taskEntry | Add-Member NoteProperty name ($taskEntry.partition + '.img') }
        Assert-Entry $taskEntry
    }
    Assert-Set @($taskBaseline.partition) $taskAllowed 'sealed baseline'
    Assert-Set @($taskReview.baseline_partitions.partition) $taskAllowed 'candidate baseline'
    foreach ($taskEntry in @($taskReview.baseline_partitions) + @($taskReview.unchanged_partition_files)) {
        Assert-Entry $taskEntry
        $taskSealed = @($taskBaseline | Where-Object partition -CEQ $taskEntry.partition)
        if ($taskSealed.Count -ne 1 -or $taskSealed[0].bytes -ne $taskEntry.bytes -or
            $taskSealed[0].sha256 -cne $taskEntry.sha256) { throw 'Candidate baseline or retained partition changed.' }
    }
    Assert-Set @($taskReview.unchanged_partition_files.partition) @($taskAllowed | Where-Object { $_ -cnotin $taskUpdated }) 'retained partitions'
    Assert-Set @($taskReview.unchanged_boot_dependencies) @() 'extra dependencies'
    $taskImages = @{}
    foreach ($taskEntry in $taskReview.files) {
        Assert-Entry $taskEntry
        $taskPath = Join-Path $taskBatch $taskEntry.name
        Assert-File $taskPath $taskEntry.bytes $taskEntry.sha256
        $taskImages[$taskEntry.partition] = $taskPath
    }
    $taskReceipt.package_verified = $true
    $taskReceipt.manifest_sha256 = (Get-FileHash -LiteralPath $taskManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Assert-Android
    if ($taskReview.runtime_inputs_receipt -cnotmatch '^reports/device/20261114-stylus-service/[A-Za-z0-9_-]+/receipt\.json$') {
        throw 'Unexpected live VINTF input receipt path.'
    }
    $taskRuntimePath = Join-Path $taskWorkspace $taskReview.runtime_inputs_receipt
    Assert-File $taskRuntimePath $null $taskReview.runtime_inputs_receipt_sha256
    $taskRuntime = Get-Content -LiteralPath $taskRuntimePath -Raw | ConvertFrom-Json
    if ($taskRuntime.passed -cne $true -or $taskRuntime.baseline_vintf_compatible -cne $true -or
        $taskRuntime.serial -cne 'ca10ede3' -or $taskRuntime.device_changed -cne $false) {
        throw 'The live VINTF cache is not qualified.'
    }
    $taskRuntimeInputs = @($taskRuntime.inputs.PSObject.Properties)
    if (-not $taskRuntimeInputs.Count) { throw 'Live VINTF input hashes are missing.' }
    foreach ($taskInput in $taskRuntimeInputs) {
        if ($taskInput.Name -cnotmatch '^/[A-Za-z0-9_./@+-]+$' -or $taskInput.Name -match '(^|/)\.\.(/|$)' -or
            $taskInput.Value -cnotmatch '^[0-9a-f]{64}$') { throw 'Unsafe live VINTF input path or hash.' }
    }
    $taskLiveHashes = @{}
    $taskLiveHashText = Invoke-Target $taskAdb @('shell', ('sha256sum ' + ($taskRuntimeInputs.Name -join ' ')))
    foreach ($taskLine in ($taskLiveHashText -split '\r?\n' | Where-Object { $_.Trim() })) {
        if ($taskLine -cnotmatch '^([0-9a-f]{64})\s+(/.+)$') { throw 'Invalid live VINTF hash response.' }
        $taskLiveHashes[$Matches[2]] = $Matches[1]
    }
    if ($taskLiveHashes.Count -ne $taskRuntimeInputs.Count) { throw 'Live VINTF input count changed.' }
    foreach ($taskInput in $taskRuntimeInputs) {
        if ($taskLiveHashes[$taskInput.Name] -cne $taskInput.Value) { throw ('Live VINTF input changed: ' + $taskInput.Name) }
    }
    $taskReceipt.live_vintf_inputs_verified = $true
    foreach ($taskEntry in $taskBaseline) { Assert-LivePartition $taskEntry }
    $taskReceipt.live_baseline_verified = $true
    Write-Output 'r65 frozen service, partition chain and all fourteen live r64 baseline hashes verified.'
    if ($Flash) {
        Invoke-Target $taskAdb @('reboot','fastboot') | Write-Output
        Wait-Fastboot $true
        foreach ($taskPart in @('system','system_ext','product','vendor')) {
            Invoke-Target $taskFastboot @('flash',($taskPart + '_a'),$taskImages[$taskPart]) | Write-Output
            $taskReceipt.flashed_partitions += $taskPart
        }
        Invoke-Target $taskFastboot @('reboot','bootloader') | Write-Output
        Wait-Fastboot $false
        if ((Invoke-Target $taskFastboot @('getvar','unlocked')) -cnotmatch '(?m)^unlocked:\s*yes\s*$') { throw 'Locked bootloader.' }
        foreach ($taskPart in @('vbmeta_system','vbmeta')) {
            Invoke-Target $taskFastboot @('flash',($taskPart + '_a'),$taskImages[$taskPart]) | Write-Output
            $taskReceipt.flashed_partitions += $taskPart
        }
        Invoke-Target $taskFastboot @('reboot') | Write-Output
        $taskDeadline = [DateTime]::UtcNow.AddSeconds(180)
        do {
            Start-Sleep -Seconds 3
            try { Assert-Android -RestoreDebugRoot; $taskReady = $true } catch { $taskReady = $false; $taskFailure = $_ }
        } while (-not $taskReady -and [DateTime]::UtcNow -lt $taskDeadline)
        if (-not $taskReady) { throw $taskFailure }
        foreach ($taskEntry in @($taskReview.files) + @($taskReview.unchanged_partition_files)) {
            Assert-LivePartition $taskEntry
            $taskReceipt.postboot_partitions_verified += $taskEntry.partition
        }
        Assert-Set @($taskReceipt.postboot_partitions_verified) $taskAllowed 'postboot partition verification'
        Write-Output 'r65 written to A; Android is Enforcing and all fourteen postboot partition hashes match.'
    }
    $taskReceipt.completed = $true
} catch {
    $taskReceipt.error = $_.ToString()
    throw
} finally {
    $taskReceipt.finished_utc = [DateTime]::UtcNow.ToString('o')
    $taskReceipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $taskEvidence 'receipt.json') -Encoding UTF8
    Write-Output ('Evidence: ' + $taskEvidence)
}
