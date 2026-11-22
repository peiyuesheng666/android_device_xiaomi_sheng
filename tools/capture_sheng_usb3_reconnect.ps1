[CmdletBinding()]
param([string]$Serial='ca10ede3',[ValidateRange(10,180)][int]$Seconds=60,[switch]$PreflightOnly)
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$adb=Join-Path $root 'tools/platform-tools/adb.exe'
$product=(& $adb -s $Serial shell getprop ro.product.device | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $product -ne 'sheng'){throw 'Expected connected sheng; capture not started.'}
$admin=([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if($PreflightOnly){[pscustomobject]@{Serial=$Serial;Product=$product;Administrator=$admin;TraceStarted=$false};return}
if(!$admin){throw 'Run in an administrator PowerShell; no trace started.'}
$id='sheng-usb-'+[guid]::NewGuid().ToString('N'); $dir=New-Item -ItemType Directory (Join-Path $root "reports/$id")
function Snapshot($label){
 $before=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
 $lines=& $adb -s $Serial shell 'cat /proc/sys/kernel/random/boot_id /proc/uptime /sys/class/udc/*/current_speed /sys/class/udc/*/state' 2>&1
 $rc=$LASTEXITCODE; [ordered]@{before_ms=$before;after_ms=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds();rc=$rc;lines=@($lines | ForEach-Object {"$_"})}|ConvertTo-Json|Set-Content (Join-Path $dir "$label.json")
}
Snapshot 'before'; $etl=Join-Path $dir 'hub.etl'; & logman start $id -p Microsoft-Windows-USB-USBHUB3 -o $etl -f bincirc -max 32 -ets
if($LASTEXITCODE -ne 0){throw 'USBHUB3 trace failed; do not switch modes.'}
try {
 Write-Host "Trace active for $Seconds seconds. When no transfer is active, manually toggle MTP once and leave it enabled."
 Start-Sleep -Seconds $Seconds
} finally { & logman stop $id -ets; if($LASTEXITCODE -ne 0){Write-Warning "Could not stop trace $id"} }
Snapshot 'after'
foreach($stream in @('dmesg','ipc')){
 $cmd=if($stream -eq 'ipc'){'cat /sys/kernel/debug/ipc_logging/a600000.ssusb/log'}else{'dmesg | grep -Ei "PS5169|dwc3|ssphy|USB_STATE|SuperSpeed"'}
 & $adb -s $Serial shell $cmd > (Join-Path $dir "$stream.txt"); if($LASTEXITCODE -ne 0){Write-Warning "$stream unavailable; retain ETL"}
}
Write-Host "Capture directory: $dir"
