# SPDX-License-Identifier: Apache-2.0
param(
    [Parameter(Mandatory=$true)][ValidateSet('Apply', 'Reclaim', 'Restore')][string]$Mode,
    [Parameter(Mandatory=$true)][string]$ReceiptDirectory,
    [ValidateSet(8,10,12)][int]$MemoryGiB = 12
)
$ErrorActionPreference = 'Stop'
$taskConfigPath = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.wslconfig'
$taskReceiptPath = Join-Path $ReceiptDirectory 'receipt.json'
$taskBackupPath = Join-Path $ReceiptDirectory 'wslconfig.original'
$taskHash = { param([byte[]]$Bytes) ([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant() }

function Assert-COnlySwap([byte[]]$Bytes) {
    $taskSwapText = [Text.Encoding]::UTF8.GetString($Bytes)
    if ([regex]::Matches($taskSwapText, '(?im)^\s*swap\s*=\s*0(?:MB|GB)?\s*$').Count -ne 1 -or
        [regex]::IsMatch($taskSwapText, '(?im)^\s*swapFile\s*=\s*(?!C:)[^\r\n]+')) {
        throw 'C-only swap policy requires swap=0 and rejects non-C swapFile settings, including old E: backups'
    }
}

function Assert-IdleWsl {
    $taskRunning = @((& wsl.exe --list --running --quiet) -replace "`0", '' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect running WSL distributions' }
    if (@($taskRunning | Where-Object { $_ -ne 'Ubuntu-22.04' }).Count) {
        throw 'Another WSL distribution is running; refusing a shared VM restart'
    }
    if ($taskRunning -contains 'Ubuntu-22.04') {
        $taskProcesses = @((& wsl.exe -d Ubuntu-22.04 -- ps -eo comm=) | ForEach-Object { $_.Trim() } | Where-Object { $_ })
        if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect guest processes' }
        $taskUnexpected = @($taskProcesses | Where-Object { $_ -notmatch '^(init.*|SessionLeader.*|Relay.*|plan9|ps)$' })
        if ($taskUnexpected.Count) { throw ('WSL is busy: ' + ($taskUnexpected -join ', ')) }
    }
}

if ($Mode -eq 'Apply') {
    if (Test-Path -LiteralPath $ReceiptDirectory) { throw 'Receipt directory already exists' }
    Assert-IdleWsl
    $taskBefore = [IO.File]::ReadAllBytes($taskConfigPath)
    Assert-COnlySwap $taskBefore
    $taskText = [Text.Encoding]::UTF8.GetString($taskBefore)
    if ([regex]::Matches($taskText, '(?m)^memory=20GB\r?$').Count -ne 1) {
        throw 'Expected the existing 20 GB WSL setting'
    }
    $taskChangedText = [regex]::Replace($taskText, '(?m)^memory=20GB(?=\r?$)', ('memory=' + $MemoryGiB + 'GB'))
    $taskAfter = [Text.Encoding]::UTF8.GetBytes($taskChangedText)
    $null = New-Item -ItemType Directory -Path $ReceiptDirectory
    [IO.File]::WriteAllBytes($taskBackupPath, $taskBefore)
    $taskReceipt = [ordered]@{
        started_utc = [DateTime]::UtcNow.ToString('o')
        config_path = $taskConfigPath
        original_sha256 = (& $taskHash $taskBefore)
        temporary_sha256 = (& $taskHash $taskAfter)
        memory_before = '20GB'
        memory_temporary = ($MemoryGiB.ToString() + 'GB')
        original_backup = $taskBackupPath
        applied = $false
        restored = $false
        device_rebooted = $false
    }
    $taskReceipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $taskReceiptPath -Encoding UTF8
    [IO.File]::WriteAllBytes($taskConfigPath, $taskAfter)
    & wsl.exe --shutdown
    if ($LASTEXITCODE -ne 0) { throw 'WSL shutdown failed; retain receipt and restore original configuration' }
    $taskReceipt.applied = $true
    $taskReceipt.applied_utc = [DateTime]::UtcNow.ToString('o')
} else {
    $taskReceipt = Get-Content -LiteralPath $taskReceiptPath -Raw | ConvertFrom-Json
    if (-not $taskReceipt.applied -or $taskReceipt.restored) { throw 'Expected an applied, unrestored configuration' }
    $taskCurrent = [IO.File]::ReadAllBytes($taskConfigPath)
    $taskOriginal = [IO.File]::ReadAllBytes($taskBackupPath)
    Assert-COnlySwap $taskCurrent
    if ($Mode -eq 'Restore') { Assert-COnlySwap $taskOriginal }
    if ((& $taskHash $taskCurrent) -ne $taskReceipt.temporary_sha256 -or
        (& $taskHash $taskOriginal) -ne $taskReceipt.original_sha256) {
        throw 'Configuration or backup changed; refusing to overwrite it'
    }
    Assert-IdleWsl
    if ($Mode -eq 'Restore') { [IO.File]::WriteAllBytes($taskConfigPath, $taskOriginal) }
    & wsl.exe --shutdown
    if ($LASTEXITCODE -ne 0) { throw 'WSL shutdown failed; retain the configuration receipt' }
    if ($Mode -eq 'Restore') {
        $taskReceipt.restored = $true
        $taskReceipt | Add-Member -NotePropertyName restored_utc -NotePropertyValue ([DateTime]::UtcNow.ToString('o'))
    } else {
        $taskReclaims = @($taskReceipt.reclaim_utc | Where-Object { $_ }) + @([DateTime]::UtcNow.ToString('o'))
        $taskReceipt | Add-Member -Force -NotePropertyName reclaim_utc -NotePropertyValue $taskReclaims
    }
}
$taskReceipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $taskReceiptPath -Encoding UTF8
$taskReceipt | ConvertTo-Json -Depth 5
