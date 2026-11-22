#!/usr/bin/env python3
"""Back up the connected sheng's active vendor_boot without changing the tablet."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--name', default='dp-usb-kernel-20261118')
parser.add_argument('--serial', default='192.168.1.139:5555')
args = parser.parse_args()
workspace = Path(__file__).resolve().parents[4]
adb = [str(workspace / 'tools/platform-tools/adb.exe'), '-s', args.serial]
shell = lambda command: subprocess.check_output(adb + ['shell', command], timeout=40).decode().strip()
assert shell('getprop ro.serialno') == 'ca10ede3'
assert shell('getprop ro.product.device') == 'sheng'
assert 'uid=0(' in shell('id')
slot = shell('getprop ro.boot.slot_suffix')
assert slot in ('_a', '_b')
source = '/dev/block/by-name/vendor_boot' + slot
expected = shell('sha256sum ' + source).split()[0]
artifact = workspace / 'artifacts' / args.name
artifact.mkdir(parents=True, exist_ok=True)
target = artifact / ('vendor_boot' + slot + '.before.img')
if not target.exists():
    with target.open('xb') as stream:
        subprocess.run(adb + ['exec-out', 'cat', source], stdout=stream, check=True, timeout=120)
assert hashlib.sha256(target.read_bytes()).hexdigest() == expected
for name in ('msm_drm', 'phy-msm-ssusb-qmp'):
    module = artifact / (name + '.before.ko')
    current = shell('sha256sum /vendor/lib/modules/' + name + '.ko').split()[0]
    if not module.exists():
        with module.open('xb') as stream:
            subprocess.run(adb + ['exec-out', 'cat', '/vendor/lib/modules/' + name + '.ko'],
                           stdout=stream, check=True, timeout=60)
    assert hashlib.sha256(module.read_bytes()).hexdigest() == current
receipt = dict(device='ca10ede3', slot=slot, remote=source, sha256=expected, bytes=target.stat().st_size)
report_name = 'dp-usb-kernel-baseline-20261118' if args.name == 'dp-usb-kernel-20261118' else args.name + '-baseline'
(workspace / 'reports' / (report_name + '.json')).write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2))
