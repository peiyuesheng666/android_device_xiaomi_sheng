# Bounded combined MIPP / real HID / supplied THP diagnostic, ca10ede3 A only.
param([switch]$InitializationOnly, [ValidateSet(0,120)][int]$PanelRefreshRate = 0,
    [switch]$DisplayRateVote, [string]$DisplayVoteBuildDirectory = '',
    [switch]$PanelMotionHandshake, [switch]$SubscribePressureReport, [switch]$SubscribeAfterUndock)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$adb = Join-Path $repo 'tools/platform-tools/adb.exe'
if($SubscribeAfterUndock -and (-not $SubscribePressureReport -or $InitializationOnly)) {
    throw 'Undock subscription requires a full pressure-subscription trial'
}
if ($DisplayRateVote -and $PanelRefreshRate -ne 0) {
    throw 'Choose either a temporary Settings trial or the display-token trial'
}
if ($DisplayRateVote -and -not $DisplayVoteBuildDirectory) {
    throw 'The exact display diagnostic build directory is required'
}
if (($PanelMotionHandshake -or $SubscribePressureReport) -and -not $DisplayRateVote -and $PanelRefreshRate -ne 120) {
    throw 'The protocol candidates require the verified 120 Hz display prerequisite'
}
$output = Join-Path $repo ('reports/device/20261111-simple/r53-pro-pressure-live-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $output | Out-Null
$identity = & $adb -s ca10ede3 shell 'getprop ro.boot.slot_suffix; getprop ro.build.fingerprint; getenforce'
if ($LASTEXITCODE -ne 0 -or $identity[0] -ne '_a' -or $identity[1] -notlike 'Xiaomi/lineage_sheng/sheng:*' -or $identity[2] -ne 'Enforcing') {
    throw 'Authorized A-slot Enforcing target unavailable'
}
$identity | Set-Content -Encoding utf8 (Join-Path $output 'identity.txt')
function Save-PenControllerEvidence([string]$phase) {
    # Keep the complete pen-only context: tail filtering can lose initialization
    # when normal finger commands and repeated dock notifications fill the log.
    & $adb -s ca10ede3 shell 'dmesg | grep -E "NVT-ts.*(nvt_set_cur_value.*mode:(20|22|29|37),|update_pen_status|nvt_set_extend_custom_cmd|nvt_get_fw_info|update_firmware_request|nvt_ts_resume|nvt_ts_suspend)|pen_charge_connect is"' |
        Set-Content -Encoding utf8 (Join-Path $output ("pen-controller-full-$phase.txt"))
    & $adb -s ca10ede3 shell 'dmesg | grep -E "NVT-ts.*(nvt_set_cur_value|update_pen_status|nvt_set_extend_custom_cmd|nvt_get_fw_info|update_firmware_request|nvt_ts_resume|nvt_ts_suspend)|pen_charge_connect is" | tail -160' |
        Set-Content -Encoding utf8 (Join-Path $output ("controller-$phase.txt"))
    & $adb -s ca10ede3 shell 'cat /sys/class/drm/card0-DSI-1/dpms; cat /sys/class/qcom-battery/pen_hall3; cat /sys/class/qcom-battery/pen_hall4; cat /sys/class/touch/touch_dev/pen_connect_strategy' |
        Set-Content -Encoding utf8 (Join-Path $output ("pen-state-$phase.txt"))
}
Save-PenControllerEvidence 'before'
$previousTimeout = (& $adb -s ca10ede3 shell settings get system screen_off_timeout).Trim()
if ($previousTimeout -notmatch '^\d+$') { throw 'Cannot preserve original screen timeout' }
[ordered]@{previous_timeout=$previousTimeout; device='ca10ede3'; slot='_a';
    display_rate_vote=[bool]$DisplayRateVote; panel_motion_candidate=[bool]$PanelMotionHandshake;
    pressure_subscription_candidate=[bool]$SubscribePressureReport;
    pressure_subscription_after_undock=[bool]$SubscribeAfterUndock} |
    ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $output 'ownership-before.json')
$bridgePid = $null
$mippStarted = $false
$remoteMippPath = '/data/local/tmp/' + (Split-Path $output -Leaf) + '-mipp.log'
$inputRestoreSucceeded = $true
$displayVotePid = $null
$displayVoteCleanup = $null
$cleanupSucceeded = $false
$refreshBefore = @{}
$refreshChanged = @{}
$refreshRestored = @{}
Write-Output $output
Copy-Item -LiteralPath (Join-Path $repo 'reports/device/20261111-simple/r52-pen-info-probe-build/build-receipt.json') -Destination (Join-Path $output 'java-build-receipt.json')
$probeInputs = [ordered]@{binary=@{}; source=@{}}
foreach ($file in @('sheng-pen-pressure-probe','sheng-pen-touchctl-probe')) {
    $probeInputs.binary[$file] = (Get-FileHash -LiteralPath (Join-Path $repo "reports/device/20261111-simple/r52-pen-info-probe-build/$file") -Algorithm SHA256).Hash
}
foreach ($file in @('sheng_pen_pressure_probe.c','sheng_pen_touchctl_probe.c','ShengPenGattInspect.java','ShengPenPanelObserver.java')) {
    $probeInputs.source[$file] = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $file) -Algorithm SHA256).Hash
}
$probeInputs | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 (Join-Path $output 'probe-inputs.json')
try {
    # Preserve the original timeout; the user's physical writing test needs a lit panel.
    & $adb -s ca10ede3 shell settings put system screen_off_timeout 600000
    if ($LASTEXITCODE -ne 0) { throw 'Temporary timeout failed' }
    & $adb -s ca10ede3 shell input keyevent 224
    if ($DisplayRateVote) {
        $receiptPath = Join-Path $DisplayVoteBuildDirectory 'build.json'
        $dexPath = Join-Path $DisplayVoteBuildDirectory 'dex/classes.dex'
        $receipt = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
        $expectedHash = (Get-FileHash -LiteralPath $dexPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $installedHash = (& $adb -s ca10ede3 shell sha256sum /data/local/tmp/sheng-pen-display-vote.dex).Split(' ')[0]
        if ($LASTEXITCODE -ne 0 -or $expectedHash -ne $installedHash -or
                $expectedHash -ne $receipt.dex_sha256.ToLowerInvariant()) {
            throw 'Installed display DEX does not match the selected build'
        }
        Copy-Item -LiteralPath $receiptPath -Destination (Join-Path $output 'display-vote-build.json')
        foreach ($key in @('min_refresh_rate','peak_refresh_rate')) {
            $refreshBefore[$key] = (& $adb -s ca10ede3 shell settings get system $key).Trim()
            if ($LASTEXITCODE -ne 0) { throw "Cannot preserve evidence for $key" }
        }
        $existing = & $adb -s ca10ede3 shell 'ps -A | grep org.lineageos.sheng.diagnostics.ShengPenDisplayVoteProbe'
        if ($existing) { throw 'Another display-vote diagnostic is already running' }
        $displayVotePid = (& $adb -s ca10ede3 shell 'SHENG_PEN_DISPLAY_VOTE_SECONDS=900 /data/local/tmp/sheng-pen-display-vote --120hz > /data/local/tmp/sheng-pen-display-vote-trial.log 2>&1 < /dev/null & echo $!').Trim()
        if ($displayVotePid -notmatch '^\d+$') { throw 'No exact display-vote PID returned' }
        $refreshDeadline = (Get-Date).AddSeconds(10)
        do {
            $display = & $adb -s ca10ede3 shell dumpsys display
            if ($LASTEXITCODE -ne 0) { throw 'Cannot read actual display mode' }
            if (($display -join "`n") -match 'mActiveSfDisplayMode=.*peakRefreshRate=120\.') { break }
            Start-Sleep -Milliseconds 500
        } while ((Get-Date) -lt $refreshDeadline)
        $display | Set-Content -Encoding utf8 (Join-Path $output 'display-before-trial.txt')
        if (($display -join "`n") -notmatch 'mActiveSfDisplayMode=.*peakRefreshRate=120\.') {
            throw 'Display token did not produce actual 120 Hz; do not initialize MIPP'
        }
        [ordered]@{requested_hz=120; before=$refreshBefore; actual_mode_verified=$true;
            display_token_pid=$displayVotePid; refresh_settings_writes=0;
            mipp_source_changed=$false; permanent_service_installed=$false} |
            ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $output 'display-trial.json')
    }
    if ($PanelRefreshRate -eq 120) {
        # The stock sheng compositor restricts an active pen to its supported
        # FPS list (default 120,60). Test that display prerequisite independently
        # of the unchanged MIPP profile and pressure collector.
        foreach ($key in @('min_refresh_rate','peak_refresh_rate')) {
            $previous = (& $adb -s ca10ede3 shell settings get system $key).Trim()
            if ($LASTEXITCODE -ne 0 -or $previous -notmatch '^(null|[0-9]+(?:\.[0-9]+)?)$') {
                throw "Cannot preserve $key"
            }
            $refreshBefore[$key] = $previous
        }
        foreach ($key in @('min_refresh_rate','peak_refresh_rate')) {
            & $adb -s ca10ede3 shell settings put system $key 120.0
            if ($LASTEXITCODE -ne 0) { throw "Temporary $key failed" }
            $refreshChanged[$key] = $true
        }
        $refreshDeadline = (Get-Date).AddSeconds(10)
        do {
            $display = & $adb -s ca10ede3 shell dumpsys display
            if ($LASTEXITCODE -ne 0) { throw 'Cannot read actual display mode' }
            if (($display -join "`n") -match 'mActiveSfDisplayMode=.*peakRefreshRate=120\.') { break }
            Start-Sleep -Milliseconds 500
        } while ((Get-Date) -lt $refreshDeadline)
        $display | Set-Content -Encoding utf8 (Join-Path $output 'display-before-trial.txt')
        if (($display -join "`n") -notmatch 'mActiveSfDisplayMode=.*peakRefreshRate=120\.') {
            throw 'Actual panel did not enter 120 Hz; do not run MIPP trial'
        }
        [ordered]@{requested_hz=120; before=$refreshBefore; actual_mode_verified=$true;
            mipp_source_changed=$false; writing_fixed=$false} |
            ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $output 'display-trial.json')
    }
    $bridgePid = (& $adb -s ca10ede3 shell '/data/local/tmp/sheng-pen-pressure-probe forward > /data/local/tmp/sheng-pen-pressure-r53.log 2>&1 < /dev/null & echo $!').Trim()
    if ($bridgePid -notmatch '^\d+$') { throw 'No exact pressure-probe PID returned' }
    $initializeOnly = if ($InitializationOnly) { 'SHENG_PEN_INITIALIZATION_ONLY=1 ' } else { '' }
    $motion = if ($PanelMotionHandshake) { 'SHENG_PEN_PANEL_MOTION=1 ' } else { '' }
    $pressureSubscription = if ($SubscribePressureReport) { 'SHENG_PEN_REPORT5_SUBSCRIBE=1 ' } else { '' }
    if($SubscribeAfterUndock) { $pressureSubscription += 'SHENG_PEN_SUBSCRIBE_AFTER_UNDOCK=1 ' }
    [ordered]@{pressure_pid=$bridgePid; display_vote_pid=$displayVotePid;
        previous_timeout=$previousTimeout} | ConvertTo-Json |
        Set-Content -Encoding utf8 (Join-Path $output 'owned-processes.json')
    $mippStarted = $true
    & $adb -s ca10ede3 shell ('set -o pipefail; ' + $initializeOnly + $motion + $pressureSubscription + 'SHENG_PEN_INSPECT=1 SHENG_PEN_INITIALIZE=1 /data/local/tmp/sheng-pen-probe --scan 28:CE:15:31:70:0E 2>&1 | tee ' + $remoteMippPath) > (Join-Path $output 'mipp.txt') 2>&1
    $trialResult = $LASTEXITCODE
} finally {
    # An interrupted USB session must not turn a failed read into a null Trim
    # error that skips every remaining restoration. Keep evidence on device.
    $reconnectDeadline=(Get-Date).AddSeconds(120)
    do {
        $target=@(& $adb -s ca10ede3 shell 'getprop ro.boot.slot_suffix; getenforce')
        $targetReady=$LASTEXITCODE -eq 0 -and $target.Count -eq 2 -and
            $target[0] -eq '_a' -and $target[1] -eq 'Enforcing'
        if($targetReady) {break}
        Start-Sleep -Seconds 2
    } while((Get-Date) -lt $reconnectDeadline)
    if(-not $targetReady) {
        [ordered]@{cleanup_succeeded=$false; pending_reason='Target unavailable after USB interruption';
            previous_timeout=$previousTimeout; pressure_pid=$bridgePid; display_vote_pid=$displayVotePid} |
            ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $output 'cleanup-pending.json')
        throw 'Target unavailable: owned diagnostic cleanup is pending'
    }
    if($mippStarted) {
        & $adb -s ca10ede3 pull $remoteMippPath (Join-Path $output 'mipp-on-device.txt')
    }
    if ($bridgePid -match '^\d+$') {
        $ownedCommand = & $adb -s ca10ede3 shell "cat /proc/$bridgePid/cmdline 2>/dev/null"
        if (($ownedCommand -join '') -like '*sheng-pen-pressure-probe*') {
            & $adb -s ca10ede3 shell "kill -TERM $bridgePid"
        }
    }
    & $adb -s ca10ede3 pull /data/local/tmp/sheng-pen-pressure-r53.log (Join-Path $output 'pressure.txt')
    # Restore the owned controller state before returning the timeout to normal.
    # A locked panel can have a separate 10-second WM override; never write Off.
    $cleanupDeadline = (Get-Date).AddSeconds(120)
    $cleanupResult = @()
    $mippPath = Join-Path $output 'mipp-on-device.txt'
    if(-not (Test-Path -LiteralPath $mippPath)) { $mippPath=Join-Path $output 'mipp.txt' }
    $mippText = if (Test-Path -LiteralPath $mippPath) { Get-Content -Raw -LiteralPath $mippPath } else { '' }
    $connectionAcquired = $mippText -match 'pen_ioctl mode=20 value=24 result=0'
    $liveGatt=& $adb -s ca10ede3 shell 'ps -A -o ARGS | grep "^app_process /system/bin org.lineageos.sheng.diagnostics.ShengPenBleProbe"'
    if($liveGatt) { throw 'GATT still owns the controller; wait for its bounded cleanup before retrying' }
    $readyRestored = -not $connectionAcquired -or $mippText -match 'Restore ready=true'
    $disconnectRestored = -not $connectionAcquired -or $mippText -match 'Restore ready=\w+ disconnect=true'
    if ($readyRestored -and $disconnectRestored -and $connectionAcquired) {
        $cleanupSucceeded = $true
        $cleanupResult = @('Java restored its owned connection; no duplicate disconnect sent')
    } elseif (-not $connectionAcquired) {
        $cleanupSucceeded = $true
        $cleanupResult = @('No successful controller connection was acquired; no disconnect sent')
    }
    if (-not $cleanupSucceeded) {
        if ((& $adb -s ca10ede3 shell cat /sys/class/drm/card0-DSI-1/dpms).Trim() -ne 'On') {
            & $adb -s ca10ede3 shell input keyevent 224
        }
        do {
            $panelState = (& $adb -s ca10ede3 shell cat /sys/class/drm/card0-DSI-1/dpms).Trim()
            if ($panelState -eq 'On') {
                Start-Sleep -Milliseconds 1100
                if (-not $readyRestored) {
                    $lastCleanup = & $adb -s ca10ede3 shell '/data/local/tmp/sheng-pen-touchctl-probe ready 0'
                    $cleanupResult += $lastCleanup
                    $readyRestored = $LASTEXITCODE -eq 0 -and ($lastCleanup -join "`n") -match 'pen_ioctl mode=37 value=0 result=0'
                }
                if (-not $disconnectRestored) {
                    $lastCleanup = & $adb -s ca10ede3 shell '/data/local/tmp/sheng-pen-touchctl-probe disconnect 8'
                    $cleanupResult += $lastCleanup
                    $disconnectRestored = $LASTEXITCODE -eq 0 -and ($lastCleanup -join "`n") -match 'pen_ioctl mode=20 value=8 result=0'
                }
                if ($readyRestored -and $disconnectRestored) {
                    $cleanupSucceeded = $true; break
                }
            }
            Start-Sleep -Seconds 1
        } while ((Get-Date) -lt $cleanupDeadline)
    }
    $cleanupResult | Set-Content -Encoding utf8 (Join-Path $output 'cleanup.txt')
    if($connectionAcquired) {
        & $adb -s ca10ede3 shell 'CLASSPATH=/data/local/tmp/sheng-pen-ble-r53.dex app_process /system/bin org.lineageos.sheng.diagnostics.ShengPenInputRestoreProbe --restore-pro-hid' |
            Set-Content -Encoding utf8 (Join-Path $output 'input-restoration.txt')
        $inputRestoreSucceeded=$LASTEXITCODE -eq 0
    }
    if ($displayVotePid -match '^\d+$') {
        $ownedCommand = & $adb -s ca10ede3 shell "cat /proc/$displayVotePid/cmdline 2>/dev/null"
        if (($ownedCommand -join '') -like '*org.lineageos.sheng.diagnostics.ShengPenDisplayVoteProbe*') {
            & $adb -s ca10ede3 shell "kill -TERM $displayVotePid"
        }
        $releaseDeadline = (Get-Date).AddSeconds(10)
        do {
            $remaining = & $adb -s ca10ede3 shell "cat /proc/$displayVotePid/cmdline 2>/dev/null"
            if (($remaining -join '') -notlike '*org.lineageos.sheng.diagnostics.ShengPenDisplayVoteProbe*') { break }
            Start-Sleep -Milliseconds 250
        } while ((Get-Date) -lt $releaseDeadline)
        $displayVoteCleanup = ($remaining -join '') -notlike '*org.lineageos.sheng.diagnostics.ShengPenDisplayVoteProbe*'
        & $adb -s ca10ede3 pull /data/local/tmp/sheng-pen-display-vote-trial.log (Join-Path $output 'display-vote.txt')
        $refreshAfter = @{}
        foreach ($key in @('min_refresh_rate','peak_refresh_rate')) {
            $refreshAfter[$key] = (& $adb -s ca10ede3 shell settings get system $key).Trim()
        }
        & $adb -s ca10ede3 shell dumpsys display |
            Set-Content -Encoding utf8 (Join-Path $output 'display-after-release.txt')
        [ordered]@{before=$refreshBefore; after=$refreshAfter;
            owned_vote_process_exited=$displayVoteCleanup; refresh_settings_writes=0;
            protocol_changed=$false; permanent_service_installed=$false} |
            ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $output 'display-cleanup.json')
    }
    if ($PanelRefreshRate -eq 120) {
        & $adb -s ca10ede3 shell dumpsys display |
            Set-Content -Encoding utf8 (Join-Path $output 'display-after-trial.txt')
        foreach ($key in @('peak_refresh_rate','min_refresh_rate')) {
            if (-not $refreshChanged.ContainsKey($key)) { continue }
            $current = (& $adb -s ca10ede3 shell settings get system $key).Trim()
            if ($current -eq '120.0') {
                if ($refreshBefore[$key] -eq 'null') {
                    & $adb -s ca10ede3 shell settings delete system $key
                } else {
                    & $adb -s ca10ede3 shell settings put system $key $refreshBefore[$key]
                }
                $refreshRestored[$key] = $LASTEXITCODE -eq 0 -and
                    ((& $adb -s ca10ede3 shell settings get system $key).Trim() -eq $refreshBefore[$key])
            } else {
                $refreshRestored[$key] = 'User or another client changed the value; preserved'
            }
        }
        [ordered]@{requested_hz=120; before=$refreshBefore; restoration=$refreshRestored;
            protocol_changed=$false; writing_fixed=$false} |
            ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $output 'display-cleanup.json')
    }
    $currentTimeout = (& $adb -s ca10ede3 shell settings get system screen_off_timeout).Trim()
    if ($currentTimeout -eq '600000') {
        & $adb -s ca10ede3 shell settings put system screen_off_timeout $previousTimeout
    }
    [ordered]@{previous_timeout=$previousTimeout; restored_timeout=(& $adb -s ca10ede3 shell settings get system screen_off_timeout).Trim(); native_pid=$bridgePid; result=$trialResult; cleanup_succeeded=$cleanupSucceeded; input_restore_succeeded=$inputRestoreSucceeded; cleanup_output=$cleanupResult} |
        ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $output 'trial-receipt.json')
    Save-PenControllerEvidence 'after'
}
Get-Content (Join-Path $output 'mipp.txt') -Tail 12
Get-Content (Join-Path $output 'pressure.txt') -Tail 12
if ($trialResult -ne 0) { throw "MIPP trial failed: $trialResult" }
if (-not $cleanupSucceeded) { throw 'Owned pen controller state could not be restored while On' }
if (-not $inputRestoreSucceeded) { throw 'Owned Pro HID input restoration needs a retry' }
if ($DisplayRateVote -and -not $displayVoteCleanup) { throw 'Owned display-vote diagnostic is still running' }
