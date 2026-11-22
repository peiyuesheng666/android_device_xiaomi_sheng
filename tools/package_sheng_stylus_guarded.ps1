# SPDX-License-Identifier: Apache-2.0
param(
    [Parameter(Mandatory=$true)][string]$GuardReceipt,
    [Parameter(Mandatory=$true)][string]$ArtifactReceipt,
    [Parameter(Mandatory=$true)][string]$RuntimeInputs,
    [Parameter(Mandatory=$true)][string]$NativeWorkDirectory
)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7 is required' }
if ($NativeWorkDirectory -cnotmatch '^/root/sheng-lineage/hardware-diagnostics/[A-Za-z0-9_-]+$') {
    throw 'Use a new native Linux staging directory under the device diagnostics root'
}
$taskWorkspace = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$taskIdentity = [Guid]::NewGuid().ToString('N')
$taskReport = Join-Path $taskWorkspace ('reports/device/20261114-stylus-service/native-package-' + $taskIdentity)
$null = New-Item -ItemType Directory -Path $taskReport
$taskSamples = Join-Path $taskReport 'host-samples'
$taskStop = Join-Path $taskReport 'stop-monitor'
$taskSampler = Join-Path $PSScriptRoot 'sample_sheng_stylus_host_memory.ps1'
$taskGuard = Join-Path $PSScriptRoot 'package_sheng_stylus_guarded.py'
$taskReceipt = [ordered]@{
    started_utc = [DateTime]::UtcNow.ToString('o')
    identity = $taskIdentity
    completed = $false
    installed = $false
    native_work = $NativeWorkDirectory
    sampler_sha256 = (Get-FileHash -LiteralPath $taskSampler -Algorithm SHA256).Hash.ToLowerInvariant()
    guard_sha256 = (Get-FileHash -LiteralPath $taskGuard -Algorithm SHA256).Hash.ToLowerInvariant()
}
$taskMonitor = [Diagnostics.Process]::new()
$taskMonitor.StartInfo.FileName = (Get-Process -Id $PID).Path
$taskMonitor.StartInfo.UseShellExecute = $false
$taskMonitor.StartInfo.CreateNoWindow = $true
$taskMonitor.StartInfo.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
$taskMonitor.StartInfo.RedirectStandardOutput = $true
$taskMonitor.StartInfo.RedirectStandardError = $true
$taskStarted = $false
foreach ($taskArgument in @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
    $taskSampler,'-SampleDirectory',$taskSamples,'-StopPath',$taskStop,'-Identity',$taskIdentity)) {
    $taskMonitor.StartInfo.ArgumentList.Add($taskArgument)
}
function Convert-NativePath([string]$Path) {
    $taskResolved = (Resolve-Path -LiteralPath $Path).Path
    $taskMapped = (& wsl.exe -d Ubuntu-22.04 --exec wslpath -u $taskResolved).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $taskMapped) { throw 'Cannot map the native package input path' }
    return $taskMapped
}
try {
    if (-not $taskMonitor.Start()) { throw 'Native host sampler failed to start' }
    $taskStarted = $true
    $taskStdout = $taskMonitor.StandardOutput.ReadToEndAsync()
    $taskStderr = $taskMonitor.StandardError.ReadToEndAsync()
    $taskDeadline = [DateTime]::UtcNow.AddSeconds(15)
    while (-not (Test-Path -LiteralPath (Join-Path $taskSamples 'sample-0000000001.json'))) {
        if ($taskMonitor.HasExited) { throw ('Native sampler failed: ' + $taskStderr.Result) }
        if ([DateTime]::UtcNow -gt $taskDeadline) { throw 'Native sampler startup timed out' }
        Start-Sleep -Milliseconds 250
    }
    $taskArguments = @('-d','Ubuntu-22.04','-u','root','--exec','python3',(Convert-NativePath $taskGuard),
        '--guard',(Convert-NativePath $GuardReceipt),'--artifacts',(Convert-NativePath $ArtifactReceipt),
        '--runtime-inputs',(Convert-NativePath $RuntimeInputs),'--work',$NativeWorkDirectory,
        '--report',(Convert-NativePath $taskReport),'--host-sample-dir',(Convert-NativePath $taskSamples),
        '--host-sample-id',$taskIdentity)
    $taskReceipt.command = @('wsl.exe') + $taskArguments
    $taskReceipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $taskReport 'receipt.json') -Encoding utf8
    Write-Output ('Native packaging monitor: ' + $taskReport)
    & wsl.exe @taskArguments
    $taskReceipt.exit_code = $LASTEXITCODE
    $taskReceipt.completed = $LASTEXITCODE -eq 0
} catch {
    $taskReceipt.error = $_.ToString()
    throw
} finally {
    [IO.File]::WriteAllText($taskStop, $taskIdentity)
    if ($taskStarted -and -not $taskMonitor.HasExited -and -not $taskMonitor.WaitForExit(5000)) { $taskMonitor.Kill() }
    if ($null -ne $taskStdout) {
        [IO.File]::WriteAllText((Join-Path $taskReport 'monitor-output.txt'), $taskStdout.Result + $taskStderr.Result)
    }
    $taskReceipt.finished_utc = [DateTime]::UtcNow.ToString('o')
    $taskReceipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $taskReport 'receipt.json') -Encoding utf8
    $taskMonitor.Dispose()
}
exit $taskReceipt.exit_code
