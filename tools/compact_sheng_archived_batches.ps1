# SPDX-License-Identifier: Apache-2.0
# Reclaim NTFS allocation while preserving old image bytes and their paths.
param([ValidateSet(30,32,42,48)][int[]]$Revision = @(30,48,32,42))
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7 is required.' }
$taskWorkspace = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$taskRoot = [IO.Path]::GetFullPath((Join-Path $taskWorkspace 'artifacts'))
$taskWork = Join-Path $taskWorkspace ('reports/device/20261114-stylus-service/archive-compaction-' + [Guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $taskWork
$taskReceipt = [ordered]@{ started_utc=[DateTime]::UtcNow.ToString('o'); complete=$false; c_free_before=[IO.DriveInfo]::new('C:\').AvailableFreeSpace; images=@(); original_paths_preserved=$true; images_deleted=$false }
try {
    foreach ($taskRevision in $Revision) {
        $taskDirectory = [IO.Path]::GetFullPath((Join-Path $taskRoot ('system-hardware-followup-sheng-r' + $taskRevision)))
        if ([IO.Path]::GetDirectoryName($taskDirectory) -cne $taskRoot) { throw 'Image path escaped the artifact root.' }
        $taskBatch = Get-Item -LiteralPath $taskDirectory -Force
        if (-not $taskBatch.PSIsContainer -or ($taskBatch.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Unexpected batch directory.' }
        $taskManifest = Get-Content -LiteralPath (Join-Path $taskDirectory 'build-result.json') -Raw | ConvertFrom-Json
        if ($taskManifest.revision -ne $taskRevision) { throw 'Archived batch revision differs.' }
        foreach ($taskFile in Get-ChildItem -LiteralPath $taskDirectory -File -Filter '*.img') {
            if (($taskFile.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
                $taskFile.Name -cnotmatch '^[a-z_]+\.img$') { throw 'Unexpected image file.' }
            $taskBefore = (Get-FileHash -LiteralPath $taskFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            $taskImage = [ordered]@{ path=$taskFile.FullName; bytes=$taskFile.Length; sha256=$taskBefore; verified=$false }
            $taskReceipt.images += $taskImage
            Write-Output ('Compressing r' + $taskRevision + '/' + $taskFile.Name)
            & compact.exe /C /I /Q $taskFile.FullName | Set-Content -LiteralPath (Join-Path $taskWork ('r' + $taskRevision + '-' + $taskFile.Name + '.log')) -Encoding UTF8
            if ($LASTEXITCODE -ne 0) { throw 'NTFS compression failed.' }
            $taskCurrent = Get-Item -LiteralPath $taskFile.FullName -Force
            if ($taskCurrent.Length -ne $taskImage.bytes -or
                (Get-FileHash -LiteralPath $taskFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -cne $taskBefore) {
                throw 'Image bytes changed during NTFS compression.'
            }
            $taskImage.verified=$true
            $taskImage.compressed=[bool]($taskCurrent.Attributes -band [IO.FileAttributes]::Compressed)
            $taskReceipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $taskWork 'receipt.json') -Encoding UTF8
        }
        Write-Output ('r' + $taskRevision + ' image hashes and paths verified')
    }
    $taskReceipt.complete=$true
} catch { $taskReceipt.error=$_.ToString(); throw }
finally {
    $taskReceipt.finished_utc=[DateTime]::UtcNow.ToString('o')
    $taskReceipt.c_free_after=[IO.DriveInfo]::new('C:\').AvailableFreeSpace
    $taskReceipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $taskWork 'receipt.json') -Encoding UTF8
    Write-Output ('Compaction receipt: ' + $taskWork)
}
