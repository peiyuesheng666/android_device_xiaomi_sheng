# SPDX-License-Identifier: Apache-2.0
param(
    [ValidateSet('modules', 'graph')][string]$Phase = 'modules',
    [ValidateSet(7,9,10)][int]$ResidentGiB = 7,
    [switch]$WithMedia
)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7 is required' }
$taskWorkspace = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$taskIdentity = [Guid]::NewGuid().ToString('N')
$taskWork = Join-Path $taskWorkspace ('reports/device/20261114-stylus-service/native-host-build-' + $taskIdentity)
$null = New-Item -ItemType Directory -Path $taskWork
$taskSampleDirectory = Join-Path $taskWork 'host-samples'
$taskStopPath = Join-Path $taskWork 'stop-monitor'
$taskSampler = Join-Path $PSScriptRoot 'sample_sheng_stylus_host_memory.ps1'
$taskGuard = Join-Path $PSScriptRoot 'build_sheng_stylus_guarded.py'
$taskReceipt = [ordered]@{
    started_utc = [DateTime]::UtcNow.ToString('o')
    identity = $taskIdentity
    sample_directory = $taskSampleDirectory
    immutable_samples = $true
    sampler_sha256 = (Get-FileHash -LiteralPath $taskSampler -Algorithm SHA256).Hash.ToLowerInvariant()
    guard_sha256 = (Get-FileHash -LiteralPath $taskGuard -Algorithm SHA256).Hash.ToLowerInvariant()
    host_sample_reader_sha256 = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'sheng_stylus_host_sample.py') -Algorithm SHA256).Hash.ToLowerInvariant()
    completed = $false
}
$taskMonitor = [Diagnostics.Process]::new()
$taskMonitor.StartInfo.FileName = (Get-Process -Id $PID).Path
$taskMonitor.StartInfo.UseShellExecute = $false
$taskMonitor.StartInfo.CreateNoWindow = $true
$taskMonitor.StartInfo.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
$taskMonitor.StartInfo.RedirectStandardOutput = $true
$taskMonitor.StartInfo.RedirectStandardError = $true
$taskMonitorStarted = $false
foreach ($taskArgument in @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
    $taskSampler, '-SampleDirectory', $taskSampleDirectory, '-StopPath', $taskStopPath, '-Identity', $taskIdentity)) {
    $taskMonitor.StartInfo.ArgumentList.Add($taskArgument)
}
try {
    if (-not $taskMonitor.Start()) { throw 'Native host sampler failed to start' }
    $taskMonitorStarted = $true
    $taskMonitorOutput = $taskMonitor.StandardOutput.ReadToEndAsync()
    $taskMonitorError = $taskMonitor.StandardError.ReadToEndAsync()
    $taskReceipt.monitor_pid = $taskMonitor.Id
    $taskDeadline = [DateTime]::UtcNow.AddSeconds(15)
    while (-not (Test-Path -LiteralPath (Join-Path $taskSampleDirectory 'sample-0000000001.json'))) {
        if ($taskMonitor.HasExited) { throw ('Native sampler failed: ' + $taskMonitorError.Result) }
        if ([DateTime]::UtcNow -gt $taskDeadline) { throw 'Native sampler startup timed out' }
        Start-Sleep -Milliseconds 250
    }
    $taskMappedSample = & wsl.exe -d Ubuntu-22.04 --exec wslpath -u $taskSampleDirectory
    if ($LASTEXITCODE -ne 0 -or -not $taskMappedSample) { throw 'Cannot map native sample path to WSL' }
    $taskSampleWsl = ($taskMappedSample -join '').Trim()
    $taskMappedGuard = & wsl.exe -d Ubuntu-22.04 --exec wslpath -u $taskGuard
    if ($LASTEXITCODE -ne 0 -or -not $taskMappedGuard) { throw 'Cannot map guard path to WSL' }
    $taskGuardWsl = ($taskMappedGuard -join '').Trim()
    $taskArguments = @('-d', 'Ubuntu-22.04', '--exec', 'python3', $taskGuardWsl,
        '--phase', $Phase, '--resident-gib', "$ResidentGiB", '--poll-seconds', '2',
        '--host-sample-dir', $taskSampleWsl, '--host-sample-id', $taskIdentity)
    if ($WithMedia) { $taskArguments += '--with-media' }
    $taskReceipt.command = @('wsl.exe') + $taskArguments
    $taskReceipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $taskWork 'receipt.json') -Encoding UTF8
    Write-Output ('Native host monitor: ' + $taskWork)
    & wsl.exe @taskArguments
    $taskReceipt.build_exit_code = $LASTEXITCODE
    $taskReceipt.completed = $true
} catch {
    $taskReceipt.error = $_.ToString()
    throw
} finally {
    [IO.File]::WriteAllText($taskStopPath, $taskIdentity)
    if ($taskMonitorStarted -and -not $taskMonitor.HasExited -and -not $taskMonitor.WaitForExit(5000)) { $taskMonitor.Kill() }
    if ($null -ne $taskMonitorOutput) {
        [IO.File]::WriteAllText((Join-Path $taskWork 'monitor-output.txt'), $taskMonitorOutput.Result + $taskMonitorError.Result)
    }
    $taskReceipt.finished_utc = [DateTime]::UtcNow.ToString('o')
    $taskReceipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $taskWork 'receipt.json') -Encoding UTF8
    $taskMonitor.Dispose()
}
exit $taskReceipt.build_exit_code
