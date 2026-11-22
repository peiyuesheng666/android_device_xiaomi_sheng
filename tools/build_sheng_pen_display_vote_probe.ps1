# SPDX-License-Identifier: Apache-2.0
# Standalone, bounded display diagnostic. No normal product build is implied.
param([string]$OutputDirectory = '')
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $repo ('reports/device/20261113-full-product/pen-display-vote-probe/' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
}
$jdk = 'C:\Program Files\Android\Android Studio\jbr\bin'
$sdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
$androidJar = Join-Path $sdk 'platforms/android-37.0/android.jar'
$d8 = Join-Path $sdk 'build-tools/36.0.0/lib/d8.jar'
$frameworkJar = Join-Path $repo 'reports/device/20261111-simple/r52-pen-info-probe-build/framework.jar'
$sources = @((Join-Path $PSScriptRoot 'ShengPenDisplayVoteProbe.java'),
    (Join-Path $repo 'device/xiaomi/sheng/interfaces/input/stylus/src/org/lineageos/sheng/stylus/DisplayRateLease.java'))
foreach ($path in @($androidJar, $frameworkJar, $d8, "$jdk/javac.exe") + $sources) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing dependency: $path" }
}
New-Item -ItemType Directory -Path "$OutputDirectory/classes", "$OutputDirectory/dex" -Force | Out-Null
& "$jdk/javac.exe" -J-Xmx256m -encoding UTF-8 -source 8 -target 8 -cp "$frameworkJar;$androidJar" -d "$OutputDirectory/classes" @sources
if ($LASTEXITCODE -ne 0) { throw 'javac failed' }
& "$jdk/jar.exe" cf "$OutputDirectory/probe.jar" -C "$OutputDirectory/classes" .
if ($LASTEXITCODE -ne 0) { throw 'jar failed' }
& "$jdk/java.exe" -Xmx512m -cp $d8 com.android.tools.r8.D8 --min-api 35 --lib $androidJar --output "$OutputDirectory/dex" "$OutputDirectory/probe.jar"
if ($LASTEXITCODE -ne 0) { throw 'D8 failed' }
$receipt = [ordered]@{kind='standalone-display-vote-diagnostic'; normal_module_build=$false; sources=@{};
    dex_sha256=(Get-FileHash -LiteralPath "$OutputDirectory/dex/classes.dex" -Algorithm SHA256).Hash;
    settings_writes=0; default_window_ms=15000; optional_window_seconds=@(15,900);
    framework_jar_sha256=(Get-FileHash -LiteralPath $frameworkJar -Algorithm SHA256).Hash;
    android_jar_sha256=(Get-FileHash -LiteralPath $androidJar -Algorithm SHA256).Hash}
foreach ($source in $sources) { $receipt.sources[$source] = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash }
$receipt | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 "$OutputDirectory/build.json"
Write-Output "$OutputDirectory/dex/classes.dex"
