# SPDX-License-Identifier: Apache-2.0
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$jdk = 'C:\Program Files\Android\Android Studio\jbr\bin'
$work = Join-Path $repo 'reports/device/20261113-full-product/pen-protocol-offline'
$protocol = Join-Path $repo 'device/xiaomi/sheng/interfaces/input/stylus'
$sources = @("$protocol/src/org/lineageos/sheng/stylus/PenModel.java",
    "$protocol/src/org/lineageos/sheng/stylus/MippProfile.java",
    "$protocol/tests/PenProtocolOfflineTest.java")
New-Item -ItemType Directory -Force -Path "$work/classes" | Out-Null
& "$jdk/javac.exe" -J-Xmx256m --release 8 -encoding UTF-8 -d "$work/classes" @sources
if ($LASTEXITCODE -ne 0) { throw 'Protocol javac failed' }
$result = & "$jdk/java.exe" -Xmx128m -cp "$work/classes" org.lineageos.sheng.stylus.PenProtocolOfflineTest
if ($LASTEXITCODE -ne 0 -or $result -notmatch '^PASS stock_protocol_checks=') { throw 'Stock fixture checks failed' }
$result | Set-Content -Encoding utf8 "$work/test.txt"
$receipt = [ordered]@{date_utc=[DateTime]::UtcNow.ToString('o'); passed=$true;
    result=$result; normal_android_module_build=$false; ordinary_focus_pen_hardware_tested=$false;
    continuous_pressure_tested=$false; sources=@{};
    stock_profile_receipt='device/xiaomi/sheng/docs/candidates/piano-pen-reference-20261111/sheng-stock-profile-receipt.json'}
foreach ($source in $sources) { $receipt.sources[$source]=(Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash }
$receipt | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 "$work/test.json"
Write-Output $result
