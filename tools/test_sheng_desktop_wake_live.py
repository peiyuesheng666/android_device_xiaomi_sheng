#!/usr/bin/env python3
"""Exercise the real Shell wake policy; restore the original desktop choice."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--serial', required=True)
p.add_argument('--expected-serial', required=True)
a = p.parse_args()
w = Path(__file__).resolve().parents[4]
adb = [str(w / 'tools/platform-tools/adb.exe'), '-s', a.serial]
out = w / 'reports' / ('desktop-wake-live-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
out.mkdir(parents=True)
record = {'samples': [], 'serial': a.expected_serial, 'passed': False}

def shell(command):
    result = subprocess.run(adb + ['shell', command], capture_output=True, timeout=25)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    return result.stdout.decode(errors='replace').strip()

def save():
    (out / 'result.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')

assert shell('getprop ro.serialno') == a.expected_serial, 'Device identity mismatch'
original = shell('settings get global sheng_desktop_enabled')
original_mode = shell('wm get-display-windowing-mode')
match = re.search(r'display windowing mode=(fullscreen|freeform|undefined)', original_mode)
assert match, original_mode
mode = {'fullscreen': 1, 'freeform': 5, 'undefined': 0}[match[1]]
assert original in ('null', '0', '1'), original
record.update(original_choice=original, original_mode=mode)
save()
try:
    for enabled in (0, 1, 0):
        assert shell('getprop ro.serialno') == a.expected_serial
        shell('settings put global sheng_desktop_enabled ' + str(enabled))
        shell('wm set-display-windowing-mode ' + ('5' if enabled else '1'))
        shell('input keyevent KEYCODE_SLEEP')
        time.sleep(3)
        shell('input keyevent KEYCODE_WAKEUP')
        time.sleep(2)
        dump = shell('dumpsys activity service com.android.systemui/.SystemUIService WMShell')
        target = re.search(r'targetWindowingModeForDefaultDisplay=(\d+)', dump)
        actual = re.search(r'Display#0 isDesktopFirst=(true|false)', dump)
        choice = shell('settings get global sheng_desktop_enabled')
        row = dict(choice=choice, expected=enabled, target=target[1] if target else None,
                   actual=actual[1] if actual else None)
        record['samples'].append(row)
        (out / ('shell-' + str(len(record['samples'])) + '.txt')).write_text(dump, encoding='utf-8')
        save()
        assert choice == str(enabled) and row['target'] == ('5' if enabled else '1'), row
        assert row['actual'] == ('true' if enabled else 'false'), row
    record['passed'] = True
except BaseException as error:
    record['error'] = repr(error)
    save()
    raise
finally:
    try:
        assert shell('getprop ro.serialno') == a.expected_serial
        shell('settings delete global sheng_desktop_enabled' if original == 'null' else
              'settings put global sheng_desktop_enabled ' + original)
        shell('wm set-display-windowing-mode ' + str(mode))
        shell('input keyevent KEYCODE_WAKEUP')
        record['restored_choice'] = shell('settings get global sheng_desktop_enabled')
        record['restored_mode'] = shell('wm get-display-windowing-mode')
        record['restore_verified'] = record['restored_choice'] == original
    except BaseException as restore_error:
        record['restore_verified'] = False
        record['restore_error'] = repr(restore_error)
    finally:
        save()
assert record['passed'] and record['restore_verified'], record
print(json.dumps(record, ensure_ascii=False, indent=2))
print(out)
