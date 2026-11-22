param(
    [Parameter(Mandatory)][string]$Serial,
    [ValidateRange(1, 60)][int]$Samples = 12,
    [ValidateRange(0, 5000)][int]$IntervalMs = 2000,
    [switch]$Handoff
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
if ([IO.Path]::GetPathRoot($root) -ne 'C:\') { throw 'Use the C: workspace' }
$adb = Join-Path $root 'tools/platform-tools/adb.exe'
function Read-Adb {
    param([string[]]$Arguments)
    $lines = & $adb -s $Serial @Arguments
    if ($LASTEXITCODE -ne 0) { throw "ADB failed: $($Arguments -join ' ')" }
    $lines
}
if ((Read-Adb @('shell','getprop','ro.product.device')) -ne 'sheng') { throw 'Not sheng' }
if ((Read-Adb @('shell','getprop','ro.serialno')) -ne $Serial) { throw 'Unexpected hardware serial' }
$out = Join-Path $root ('reports/audio-duplex-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $out | Out-Null
if ($Handoff) { $services = @('media.audio_flinger', 'media.audio_policy') } else { $services = @('audio', 'media.audio_policy', 'media.audio_flinger') }
function Save-RouteEvents([string]$Phase) {
    Read-Adb @('shell','dumpsys','-t','4','audio') |
        Select-String -Pattern 'event:device|event:started|event:paused|event:muted|rec (update|stop)|onScoAudioStateChanged|adjustStreamVolume|setStreamVolume' |
        ForEach-Object Line | Set-Content (Join-Path $out "route-events-$Phase.txt")
}
if ($Handoff) { Save-RouteEvents 'before' }
for ($i=0; $i -lt $Samples; $i++) {
    foreach ($service in $services) {
        $file = Join-Path $out ('{0:D2}-{1}.txt' -f $i,$service)
        ('host_utc=' + [DateTime]::UtcNow.ToString('o')) | Set-Content $file
        Read-Adb @('shell','dumpsys','-t','4',$service) | Add-Content $file
    }
    if ($i + 1 -lt $Samples) { Start-Sleep -Milliseconds $IntervalMs }
}
if ($Handoff) { Save-RouteEvents 'after' }
Write-Output $out
