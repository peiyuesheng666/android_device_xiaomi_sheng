#!/usr/bin/env python3
"""Record the reviewed sheng stock profile; read-only original APK inspection."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path('/root/sheng-lineage')
DEVICE = Path(__file__).resolve().parents[1]
STOCK = ROOT / 'firmware-dump/partitions'
apk = STOCK / 'system_ext/app/BluetoothExtension/BluetoothExtension.apk'
overlay = STOCK / 'product/overlay/MiuiBtRRODeviceConfigOverlay.apk'
aapt = ROOT / 'lineage-24.0/out/host/linux-x86/bin/aapt2'
resources = subprocess.run([aapt, 'dump', 'resources', overlay], check=True,
                           capture_output=True, text=True).stdout
lines = resources.splitlines()
timestamp_lines = []
for i, line in enumerate(lines):
    if 'TIME_STAMP' in line:
        timestamp_lines.extend(lines[i:i+4])
stamp = 1692773138
if not timestamp_lines or not any(str(stamp) in s or f'{stamp:x}' in s.lower()
                                  for s in timestamp_lines):
    raise SystemExit('Original sheng TIME_STAMP does not match reviewed default branch')
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
profile = {
    'kind': 'reviewed-stock-sheng-mipp-profile',
    'device': 'sheng',
    'stock_apk': {'path': str(apk), 'sha256': digest(apk)},
    'stock_overlay': {'path': str(overlay), 'sha256': digest(overlay),
                      'time_stamp': stamp, 'resource_evidence': timestamp_lines},
    'reviewed_helper_class': 'com.android.bluetooth.ble.h',
    'default_branch_reason': 'TIME_STAMP differs from 1729760400, 1733291853, 1733283422',
    'parameter_total_bytes': 32,
    'basic_hex': 'a01e3e171a041a',
    'sequence_hex': '00000d680000052800000d68',
    'footer_hex': 'f401',
    'frequency_index0_hex': '9b6fef43',
    'voltage_value': 40,
    'source_modified': False,
    'firmware_update_performed': False,
    'writing_verified': False,
}
out = DEVICE / 'docs/candidates/piano-pen-reference-20261111/sheng-stock-profile-receipt.json'
out.write_text(json.dumps(profile, indent=2) + '\n')
print(out)
