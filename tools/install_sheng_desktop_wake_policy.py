#!/usr/bin/env python3
"""Install the qualified SystemUI candidate with a verified, atomic replacement."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess
import zipfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--serial', required=True)
p.add_argument('--expected-serial', required=True)
a = p.parse_args()
w = Path(__file__).resolve().parents[4]
folder = w / 'reports/desktop-wake-policy-20261118'
receipt = folder / 'atomic-install.json'
assert not receipt.exists(), 'Preserve the previous install receipt'
build = json.loads((folder / 'build.json').read_text())
apk = w / 'artifacts/desktop-wake-policy-20261118/SystemUI.apk'
assert hashlib.sha256(apk.read_bytes()).hexdigest() == build['candidate_sha256']
assert build['certificate_matches'] and build['resources_preserved']
with zipfile.ZipFile(apk) as archive:
    assert archive.testzip() is None
adb = [str(w / 'tools/platform-tools/adb.exe'), '-s', a.serial]
target = '/system_ext/priv-app/SystemUI/SystemUI.apk'
pending = '/system_ext/priv-app/SystemUI/.SystemUI.wake-policy.pending'
upload = '/data/local/tmp/sheng-SystemUI-wake-policy-complete.apk'
backup = '/data/local/tmp/sheng-SystemUI-before-atomic-wake-policy.apk'
record = {'serial': a.expected_serial, 'installed': False, 'rebooted': False}

def run(args, timeout=120):
    result = subprocess.run(adb + args, capture_output=True, timeout=timeout)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    return result.stdout.decode(errors='replace').strip()

def shell(command):
    return run(['shell', command])

def digest(path):
    return shell('sha256sum ' + path).split()[0]

def save():
    receipt.write_text(json.dumps(record, indent=2), encoding='utf-8')

assert shell('getprop ro.serialno') == a.expected_serial
assert 'uid=0(' in shell('id'), 'Root adbd required'
assert digest(target) == build['baseline_sha256'], 'Installed baseline differs'
assert shell('test -e ' + backup + ' && echo exists || echo absent') == 'absent'
assert shell('test -e ' + pending + ' && echo exists || echo absent') == 'absent'
record['permissions_before'] = shell('dumpsys package com.android.systemui')
for permission in ('BLUETOOTH_CONNECT', 'BLUETOOTH_SCAN', 'BLUETOOTH_ADVERTISE', 'READ_CONTACTS'):
    assert 'android.permission.' + permission + ': granted=true' in record['permissions_before']
context = re.search(r'u:object_r:[a-zA-Z0-9_]+:s0', shell('ls -lZ ' + target))
assert context, 'Cannot read target SELinux context'
record['selinux_context'] = context[0]
record['boot_id'] = shell('cat /proc/sys/kernel/random/boot_id')
save()
try:
    shell('cp ' + target + ' ' + backup)
    assert digest(backup) == build['baseline_sha256']
    record['backup_verified'] = True
    save()
    run(['push', str(apk), upload])
    assert digest(upload) == build['candidate_sha256']
    # Some builds report failure for a separate camera overlay even after
    # system_ext is writable. Verify the actual destination independently.
    remount = subprocess.run(adb + ['remount'], capture_output=True, timeout=30)
    record['remount_output'] = (remount.stdout + remount.stderr).decode(errors='replace')
    shell('test -w /system_ext/priv-app/SystemUI')
    # A dropped connection can only leave the non-APK pending file incomplete.
    # Never stream or copy over the PackageManager-visible APK.
    shell('cp ' + upload + ' ' + pending + ' && chmod 0644 ' + pending
          + ' && chown root:root ' + pending)
    assert digest(pending) == build['candidate_sha256']
    assert digest(target) == build['baseline_sha256']
    assert shell('getprop ro.serialno') == a.expected_serial
    # Android toybox chcon has no --reference option.
    shell('chcon ' + record['selinux_context'] + ' ' + pending)
    assert record['selinux_context'] in shell('ls -lZ ' + pending)
    shell('sync && mv -f ' + pending + ' ' + target + ' && sync')
    assert digest(target) == build['candidate_sha256']
    record['installed'] = True
    record['installed_sha256'] = build['candidate_sha256']
    record['note'] = 'Complete file installed. Runtime validation is a separate required step.'
except BaseException as error:
    record['error'] = repr(error)
    raise
finally:
    save()
print(receipt)
