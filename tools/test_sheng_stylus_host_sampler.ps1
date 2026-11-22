# SPDX-License-Identifier: Apache-2.0
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7 is required' }
$taskWorkspace = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$taskWork = Join-Path $taskWorkspace ('reports/device/20261114-stylus-service/host-sampler-test-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $taskWork
$taskSampler = Join-Path $PSScriptRoot 'sample_sheng_stylus_host_memory.ps1'
$taskResults = [Collections.Generic.List[object]]::new()

function Wait-Sample {
    param([string]$Path, [int]$AfterSequence, [Diagnostics.Process]$Monitor, [switch]$Immutable)
    $taskDeadline = [DateTime]::UtcNow.AddSeconds(12)
    while ([DateTime]::UtcNow -lt $taskDeadline) {
        if ($Monitor.HasExited) { throw 'Sampler exited while awaiting a fresh sample' }
        $taskReadPath = if ($Immutable) {
            @(Get-ChildItem -LiteralPath $Path -Filter 'sample-*.json' -File -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1).FullName
        } else { $Path }
        if ($taskReadPath -and (Test-Path -LiteralPath $taskReadPath)) {
            $taskValue = [IO.File]::ReadAllText($taskReadPath) | ConvertFrom-Json
            if ($taskValue.sequence -gt $AfterSequence) { return $taskValue }
        }
        Start-Sleep -Milliseconds 25
    }
    throw 'Fresh sample timed out'
}

foreach ($taskCase in @('transient-lock', 'persistent-lock', 'immutable-held-reader')) {
    $taskCaseWork = Join-Path $taskWork $taskCase
    $null = New-Item -ItemType Directory -Path $taskCaseWork
    $taskSamplePath = Join-Path $taskCaseWork 'sample.json'
    $taskImmutable = $taskCase -eq 'immutable-held-reader'
    $taskSampleSource = if ($taskImmutable) { Join-Path $taskCaseWork 'samples' } else { $taskSamplePath }
    $taskStopPath = Join-Path $taskCaseWork 'stop'
    $taskMonitor = [Diagnostics.Process]::new()
    $taskMonitor.StartInfo.FileName = (Get-Process -Id $PID).Path
    $taskMonitor.StartInfo.UseShellExecute = $false
    $taskMonitor.StartInfo.CreateNoWindow = $true
    $taskMonitor.StartInfo.RedirectStandardOutput = $true
    $taskMonitor.StartInfo.RedirectStandardError = $true
    $taskSourceArgument = if ($taskImmutable) { '-SampleDirectory' } else { '-SamplePath' }
    foreach ($taskArg in @('-NoProfile', '-NonInteractive', '-File', $taskSampler,
        $taskSourceArgument, $taskSampleSource, '-StopPath', $taskStopPath, '-Identity', $taskCase)) {
        $taskMonitor.StartInfo.ArgumentList.Add($taskArg)
    }
    $taskLock = $null
    $taskPassed = $false
    try {
        if (-not $taskMonitor.Start()) { throw 'Cannot start test sampler' }
        $taskStdout = $taskMonitor.StandardOutput.ReadToEndAsync()
        $taskStderr = $taskMonitor.StandardError.ReadToEndAsync()
        $taskInitial = Wait-Sample $taskSampleSource 1 $taskMonitor -Immutable:$taskImmutable
        if ($taskImmutable) { $taskSamplePath = Join-Path $taskSampleSource ('sample-{0:D10}.json' -f [int]$taskInitial.sequence) }
        # Sharing reads but not deletes reproduces the destination lock caused
        # by a WSL reader during Windows atomic file replacement.
        $taskLock = [IO.File]::Open($taskSamplePath, [IO.FileMode]::Open,
            [IO.FileAccess]::Read, [IO.FileShare]::Read)
        $taskHeld = [IO.File]::ReadAllText($taskSamplePath)
        $taskHoldMs = if ($taskCase -eq 'transient-lock') { 1400 } else { 3500 }
        Start-Sleep -Milliseconds $taskHoldMs
        if ([IO.File]::ReadAllText($taskSamplePath) -cne $taskHeld) {
            throw 'Locked sample contents or measured timestamp changed'
        }
        if ($taskCase -ne 'persistent-lock') {
            if ($taskMonitor.HasExited) { throw 'Short reader lock killed the sampler' }
            $taskLiveReader = $null
            if ($taskImmutable) {
                $taskMappedDirectory = (& wsl.exe -d Ubuntu-22.04 --exec wslpath -u $taskSampleSource).Trim()
                if ($LASTEXITCODE -ne 0) { throw 'Cannot map immutable samples to WSL' }
                $taskMappedTools = (& wsl.exe -d Ubuntu-22.04 --exec wslpath -u $PSScriptRoot).Trim()
                if ($LASTEXITCODE -ne 0) { throw 'Cannot map reader source to WSL' }
                $taskLiveCode = @'
import json, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from sheng_stylus_host_sample import read_host_sample
directory = Path(sys.argv[1])
sequences = []
old_path = sorted(directory.glob('sample-*.json'))[0]
with old_path.open() as held:
    old = held.read()
    for unused in range(5):
        sample = read_host_sample('immutable-held-reader', sample_directory=directory)
        sequences.append(sample['sequence'])
        time.sleep(1)
    held.seek(0)
    assert held.read() == old
assert len(set(sequences)) >= 4, sequences
print(json.dumps(dict(passed=True, sequences=sequences, old_sample_unchanged=True)))
'@
                $taskLiveOutput = & wsl.exe -d Ubuntu-22.04 --exec python3 -c $taskLiveCode $taskMappedDirectory $taskMappedTools
                if ($LASTEXITCODE -ne 0) { throw 'Live WSL held-reader verification failed' }
                $taskLiveReader = ($taskLiveOutput -join "`n") | ConvertFrom-Json
                if ([IO.File]::ReadAllText($taskSamplePath) -cne $taskHeld) { throw 'Published immutable sample changed' }
            }
            $taskLock.Dispose(); $taskLock = $null
            $taskRecovered = Wait-Sample $taskSampleSource $taskInitial.sequence $taskMonitor -Immutable:$taskImmutable
            $taskNext = Wait-Sample $taskSampleSource $taskRecovered.sequence $taskMonitor -Immutable:$taskImmutable
            if (-not $taskImmutable -and $taskNext.publish_retries -le 0) { throw 'Reader lock did not exercise publication retries' }
            if ($taskNext.identity -ne $taskCase -or $taskNext.monitor_pid -ne $taskMonitor.Id -or
                $taskNext.free_commit_bytes -le 0 -or $taskNext.c_free_bytes -le 0 -or
                [DateTime]::Parse($taskNext.date_utc) -le [DateTime]::Parse($taskInitial.date_utc)) {
                throw 'Recovered sample is invalid or did not advance'
            }
            [IO.File]::WriteAllText($taskStopPath, $taskCase)
            if (-not $taskMonitor.WaitForExit(5000) -or $taskMonitor.ExitCode -ne 0) {
                throw 'Recovered sampler did not stop normally'
            }
            $taskResults.Add(@{case=$taskCase; passed=$true; before=$taskInitial; after=$taskNext; unchanged_while_locked=$true; live_wsl_reader=$taskLiveReader; exit_code=$taskMonitor.ExitCode})
        } else {
            if (-not $taskMonitor.HasExited -or $taskMonitor.ExitCode -eq 0) {
                throw 'Persistent destination lock did not fail within the retry deadline'
            }
            if (-not (Test-Path -LiteralPath ($taskSamplePath + '.writing'))) {
                throw 'Failed publication did not preserve the pending measured sample'
            }
            $taskErrorText = $taskStderr.Result
            if ($taskErrorText -notmatch 'Move|access|访问|used by another process') {
                throw 'Persistent-lock failure did not report the publication error'
            }
            $taskResults.Add(@{case=$taskCase; passed=$true; unchanged_while_locked=$true; stale_sample=$taskInitial; exit_code=$taskMonitor.ExitCode; hold_ms=$taskHoldMs})
        }
        $taskPassed = $true
    } finally {
        if ($null -ne $taskLock) { $taskLock.Dispose() }
        [IO.File]::WriteAllText($taskStopPath, $taskCase)
        if (-not $taskMonitor.HasExited -and -not $taskMonitor.WaitForExit(5000)) { $taskMonitor.Kill(); $taskMonitor.WaitForExit() }
        if ($null -ne $taskStdout) {
            [IO.File]::WriteAllText((Join-Path $taskCaseWork 'monitor-output.txt'), $taskStdout.Result + $taskStderr.Result)
        }
        $taskMonitor.Dispose()
        if (-not $taskPassed) { Write-Output ('Failed sampler evidence: ' + $taskCaseWork) }
    }
}
$taskReceipt = [ordered]@{
    date_utc = [DateTime]::UtcNow.ToString('o')
    sampler_sha256 = (Get-FileHash -LiteralPath $taskSampler -Algorithm SHA256).Hash.ToLowerInvariant()
    passed = $true
    cases = $taskResults.ToArray()
    device_operated = $false
}
$taskReceipt | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $taskWork 'receipt.json') -Encoding UTF8
Write-Output ('Sampler tests passed: ' + $taskWork)
