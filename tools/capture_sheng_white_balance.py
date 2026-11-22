#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Trace white-balance state across a temporary CCT override, restoring it afterwards."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--drm-probe', type=Path,
                        help='Locally compiled read-only ShengDrmColorProbe executable')
    parser.add_argument('--warm-settle-seconds', type=float, default=8,
                        help='Time to observe the framework warm-temperature transition')
    args = parser.parse_args()
    if not 1 <= args.warm_settle_seconds <= 60:
        parser.error('--warm-settle-seconds must be between 1 and 60')
    root = Path(__file__).resolve().parents[4]
    adb = root / 'tools/platform-tools/adb.exe'
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    receipt = dict(started_utc=datetime.now(timezone.utc).isoformat(), restored=False,
                   screenshot_taken=False, camera_used=False, samples={})
    remote_probe = None

    def shell(label, command):
        result = subprocess.run([str(adb), '-s', 'ca10ede3', 'shell', command],
                                capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=35)
        (output / (label + '.log')).write_text(result.stdout + result.stderr, encoding='utf-8')
        result.check_returncode()
        return result.stdout

    def capture(label):
        display = shell(label + '-display', 'dumpsys display')
        colors = shell(label + '-colors', 'dumpsys color_display')
        sf = shell(label + '-surfaceflinger', 'dumpsys SurfaceFlinger')
        shell(label + '-crtc', 'cat /sys/kernel/debug/dri/0/crtc176/state')
        if remote_probe:
            shell(label + '-pcc', remote_probe)
        transform = re.search(r'current transform: \n((?:[^\n]*\n){4})', sf)
        matrix = re.search(r'colorTransformMatrix=([^\n]+)', sf)
        values = {name: re.search(r'\b' + name + r'\s*=\s*([^\n]+)', colors).group(1)
                  for name in ('mCurrentColorTemperature', 'mTargetCct', 'mAppliedCct')}
        values.update(screen=re.search(r'mScreenState=(\w+)', display).group(1),
                      override=re.search(r'mAmbientColorTemperatureOverride=([^\n]+)', display).group(1),
                      surfaceflinger_matrix=matrix.group(1).strip() if matrix else None,
                      composer_matrix=transform.group(1).strip() if transform else None)
        receipt['samples'][label] = values
        print(json.dumps(dict(sample=label, **values)), flush=True)
        return display

    def wait_awake(seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            shell('keep-awake', 'input keyevent KEYCODE_WAKEUP')
            time.sleep(min(2, max(0, deadline - time.monotonic())))

    try:
        identity = shell('identity', 'getprop ro.product.device; getprop ro.boot.slot_suffix; getenforce')
        assert identity.splitlines() == ['sheng', '_a', 'Enforcing']
        if args.drm_probe:
            binary = args.drm_probe.resolve(strict=True)
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
            remote_probe = '/data/local/tmp/sheng-drm-color-' + uuid.uuid4().hex
            subprocess.run([str(adb), '-s', 'ca10ede3', 'push', str(binary), remote_probe],
                           check=True, capture_output=True, text=True, encoding='utf-8', timeout=35)
            remote_digest = shell('probe-identity', 'sha256sum ' + remote_probe).split()[0]
            assert remote_digest == digest
            shell('probe-mode', 'chmod 0755 ' + remote_probe)
            receipt['drm_probe_sha256'] = digest
        original = capture('before')
        old_override = float(re.search(r'mAmbientColorTemperatureOverride=([^\n]+)', original).group(1))
        old_screen = receipt['samples']['before']['screen']
        assert old_screen in ('ON', 'OFF')
        try:
            shell('wake', 'input keyevent KEYCODE_WAKEUP')
            wait_awake(4)
            capture('ambient')
            for label, cct, wait in (('cool', 8100, 5),
                                     ('warm', 5300, args.warm_settle_seconds)):
                shell(label + '-override', 'cmd display dwb-set-cct ' + str(cct))
                wait_awake(wait)
                capture(label)
                assert receipt['samples'][label]['screen'] == 'ON'
        finally:
            shell('restore-override', 'cmd display dwb-set-cct ' + str(old_override))
            if old_screen == 'OFF':
                shell('restore-screen', 'input keyevent KEYCODE_SLEEP')
                time.sleep(1)
            capture('restored')
            receipt['restored'] = (float(receipt['samples']['restored']['override']) == old_override
                                   and receipt['samples']['restored']['screen'] == old_screen)
    finally:
        try:
            if remote_probe:
                shell('remove-probe', 'rm -f ' + remote_probe)
        finally:
            receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
            (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    assert receipt['restored']


if __name__ == '__main__':
    main()
