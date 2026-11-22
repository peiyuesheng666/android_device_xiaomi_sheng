# Bounded pen diagnostic build; does not require WSL.
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$jdk = 'C:\Program Files\Android\Android Studio\jbr\bin'
$sdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk'
$androidJar = Join-Path $sdk 'platforms\android-37.0\android.jar'
$d8 = Join-Path $sdk 'build-tools\36.0.0\lib\d8.jar'
$work = Join-Path $repo 'reports\device\20261111-simple\r52-pen-info-probe-build'
$frameworkJar = Join-Path $work 'framework.jar'
foreach ($path in @($androidJar, $d8, (Join-Path $jdk 'javac.exe'))) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing dependency: $path" }
}
New-Item -ItemType Directory -Force -Path "$work\classes", "$work\dex" | Out-Null
$sources = @((Join-Path $PSScriptRoot 'ShengPenBleProbe.java'),
             (Join-Path $PSScriptRoot 'ShengPenGattInspect.java'),
             (Join-Path $PSScriptRoot 'ShengPenPanelObserver.java'),
             (Join-Path $PSScriptRoot 'ShengPenHidReconnect.java'),
             (Join-Path $PSScriptRoot 'ShengPenInputRestoreProbe.java'),
             (Join-Path $repo 'device/xiaomi/sheng/interfaces/input/stylus/src/org/lineageos/sheng/stylus/PenModel.java'),
             (Join-Path $repo 'device/xiaomi/sheng/interfaces/input/stylus/src/org/lineageos/sheng/stylus/MippProfile.java'))
if (-not (Test-Path -LiteralPath $frameworkJar)) { throw 'Retained framework.jar is required for UEventObserver compilation' }
& "$jdk\javac.exe" -J-Xmx256m -encoding UTF-8 -source 8 -target 8 -cp "$frameworkJar;$androidJar" -d "$work\classes" @sources
if ($LASTEXITCODE -ne 0) { throw 'javac failed' }
& "$jdk\jar.exe" cf "$work\probe.jar" -C "$work\classes" .
if ($LASTEXITCODE -ne 0) { throw 'jar failed' }
& "$jdk\java.exe" -Xmx512m -cp $d8 com.android.tools.r8.D8 --min-api 35 --lib $androidJar --output "$work\dex" "$work\probe.jar"
if ($LASTEXITCODE -ne 0) { throw 'D8 failed' }
$receipt = [ordered]@{kind='bounded-pen-diagnostic'; default_information_only=$true; initialization_opt_in='SHENG_PEN_INITIALIZE=1'; wsl_used=$false; source=@{}; dex_sha256=(Get-FileHash -LiteralPath "$work\dex\classes.dex" -Algorithm SHA256).Hash}
foreach ($source in $sources) { $receipt.source[(Split-Path $source -Leaf)] = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash }
$receipt | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 "$work\build-receipt.json"
Write-Output "$work\dex\classes.dex"
