# SPDX-License-Identifier: Apache-2.0
param(
    [Parameter(Mandatory=$true, ParameterSetName='Replace')][string]$SamplePath,
    [Parameter(Mandatory=$true, ParameterSetName='Immutable')][string]$SampleDirectory,
    [Parameter(Mandatory=$true)][string]$StopPath,
    [Parameter(Mandatory=$true)][string]$Identity
)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7 is required for atomic sample replacement' }
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class ShengHostPerformance {
    [StructLayout(LayoutKind.Sequential)]
    private struct Info {
        public uint cb;
        public UIntPtr CommitTotal, CommitLimit, CommitPeak;
        public UIntPtr PhysicalTotal, PhysicalAvailable, SystemCache;
        public UIntPtr KernelTotal, KernelPaged, KernelNonpaged, PageSize;
        public uint HandleCount, ProcessCount, ThreadCount;
    }
    [DllImport("psapi.dll", SetLastError=true)]
    private static extern bool GetPerformanceInfo(ref Info value, uint size);
    public static ulong[] Read() {
        Info value = new Info();
        value.cb = (uint)Marshal.SizeOf(typeof(Info));
        if (!GetPerformanceInfo(ref value, value.cb)) throw new Win32Exception(Marshal.GetLastWin32Error());
        ulong page = value.PageSize.ToUInt64();
        return new ulong[] { value.CommitLimit.ToUInt64() * page, value.CommitTotal.ToUInt64() * page };
    }
}
'@
$taskImmutable = $PSCmdlet.ParameterSetName -eq 'Immutable'
if ($taskImmutable) {
    $null = [IO.Directory]::CreateDirectory($SampleDirectory)
    if ([IO.Directory]::GetFiles($SampleDirectory).Length) { throw 'Immutable sample directory must start empty' }
    $taskTemporary = Join-Path $SampleDirectory 'sample.writing'
} else {
    $taskTemporary = $SamplePath + '.writing'
}
$taskSequence = 0
$taskPublishRetries = 0
$taskDisk = [IO.DriveInfo]::new('C:\')
while (-not (Test-Path -LiteralPath $StopPath)) {
    $taskPerformance = [ShengHostPerformance]::Read()
    $taskSequence++
    $taskSample = [ordered]@{
        date_utc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.ffffff'Z'")
        identity = $Identity
        monitor_pid = $PID
        sequence = $taskSequence
        commit_limit_bytes = $taskPerformance[0]
        committed_bytes = $taskPerformance[1]
        free_commit_bytes = [long]($taskPerformance[0] - $taskPerformance[1])
        c_free_bytes = $taskDisk.AvailableFreeSpace
        measurement = 'Windows GetPerformanceInfo'
        publish_retries = $taskPublishRetries
    }
    [IO.File]::WriteAllText($taskTemporary, ($taskSample | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
    $taskDestination = if ($taskImmutable) {
        Join-Path $SampleDirectory ('sample-{0:D10}.json' -f $taskSequence)
    } else { $SamplePath }
    # A simultaneous WSL read can hold the destination without delete sharing.
    # Keep the measured timestamp and values, and fail if publication stays
    # blocked. Never restamp an old sample or bypass the supervisor's timeout.
    $taskPublishDeadline = [DateTime]::UtcNow.AddSeconds(2)
    while ($true) {
        try { [IO.File]::Move($taskTemporary, $taskDestination, (-not $taskImmutable)); break }
        catch {
            $taskFailure = $_.Exception.GetBaseException()
            $taskWin32Error = $taskFailure.HResult -band 0xffff
            if ($taskWin32Error -notin @(5,32,33) -or [DateTime]::UtcNow -ge $taskPublishDeadline) { throw }
            $taskPublishRetries++
            Start-Sleep -Milliseconds 25
        }
    }
    if ($taskImmutable) {
        # Published snapshots never change. A long-lived DrvFS reader can
        # retain an old handle without preventing publication of new samples.
        $taskOldSamples = @([IO.Directory]::EnumerateFiles($SampleDirectory, 'sample-*.json') | Sort-Object)
        foreach ($taskOldPath in ($taskOldSamples | Select-Object -SkipLast 60)) {
            try { [IO.File]::Delete($taskOldPath) }
            catch {
                $taskDeleteError = $_.Exception.GetBaseException().HResult -band 0xffff
                if ($taskDeleteError -notin @(5,32,33)) { throw }
            }
        }
    }
    Start-Sleep -Milliseconds 1000
}
