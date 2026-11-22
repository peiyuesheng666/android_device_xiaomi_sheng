#!/usr/bin/env python3
"""Stage only the independent USB power app, with hash-checked atomic replacement."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import zipfile

w = Path(__file__).resolve().parents[4]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--serial', required=True)
args = p.parse_args()
adb = w / 'tools/platform-tools/adb.exe'
report = w / 'reports/usb-power-20261118'
apk = w / 'artifacts/usb-power-20261118/ShengUsbPower.apk'
record = json.loads((report / 'build.json').read_text())
assert record['platform_certificate_matches']
assert hashlib.sha256(apk.read_bytes()).hexdigest() == record['apk_sha256']
with zipfile.ZipFile(apk) as z:
    assert z.testzip() is None

def run(*parts, check=True):
    p = subprocess.run([str(adb), '-s', args.serial, *parts], capture_output=True,
                       text=True, encoding='utf-8', errors='replace', timeout=120)
    if check and p.returncode:
        raise RuntimeError(p.stdout + p.stderr)
    return p.stdout.strip()

def shell(command):
    return run('shell', command)

assert args.serial == 'ca10ede3', 'This installer is scoped to the diagnosed tablet'
assert shell('getprop ro.serialno') == args.serial
assert shell('getprop ro.product.device') == 'sheng'
assert shell('id -u') == '0', 'Run adb root first'
ui = '/system_ext/priv-app/SystemUI/SystemUI.apk'
baseline = shell('sha256sum ' + ui).split()[0]
receipt = dict(serial=args.serial, systemui_before=baseline, staged=False,
               rebooted=False, artifacts=[])
(report / 'install.json').write_text(json.dumps(receipt, indent=2))
# Some vendor overlays remain read-only. Each actual destination is checked below.
receipt['remount'] = run('remount', check=False)
files = [(apk, '/product/app/ShengUsbPower', 'ShengUsbPower.apk'),
         (w / 'device/xiaomi/sheng/interfaces/usb/power/default-permissions-sheng-usb-power.xml',
          '/product/etc/default-permissions', 'default-permissions-sheng-usb-power.xml')]
for local, directory, name in files:
    digest = hashlib.sha256(local.read_bytes()).hexdigest()
    remote = '/data/local/tmp/sheng-usb-power-' + name
    pending = directory + '/.' + name + '.pending'
    target = directory + '/' + name
    # Do not overwrite an unrelated package or permission file.
    existing = shell('if [ -f ' + target + ' ]; then sha256sum ' + target + '; fi')
    assert not existing or existing.split()[0] == digest, 'Unexpected existing file: ' + target
    run('push', str(local), remote)
    assert shell('sha256sum ' + remote).split()[0] == digest
    shell('mkdir -p ' + directory)
    shell('cp ' + remote + ' ' + pending)
    assert shell('sha256sum ' + pending).split()[0] == digest
    shell('chown 0:0 ' + pending + ' && chmod 0644 ' + pending)
    shell('restorecon ' + pending)
    shell('sync && mv ' + pending + ' ' + target + ' && restorecon ' + target + ' && sync')
    assert shell('sha256sum ' + target).split()[0] == digest
    receipt['artifacts'].append(dict(path=target, sha256=digest))
    (report / 'install.json').write_text(json.dumps(receipt, indent=2))
receipt['systemui_after'] = shell('sha256sum ' + ui).split()[0]
assert receipt['systemui_after'] == baseline, 'SystemUI changed outside this installer'
receipt['staged'] = True
(report / 'install.json').write_text(json.dumps(receipt, indent=2))
print(json.dumps(receipt, indent=2))
