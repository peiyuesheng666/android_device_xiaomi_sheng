#!/usr/bin/env python3
"""Reject a Settings APK missing sheng's native desktop page or QS service.

This checks packaged class definitions, not source presence or UI behavior.
It never modifies the ROM tree or connects to a device.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

from sheng_apk_components import dex_classes


REQUIRED = {
    'Lcom/android/settings/sheng/DesktopModeSettings;',
    'Lcom/android/settings/sheng/DesktopModeSettings$DesktopTileService;',
}
# Private Controller implementations may be renamed or inlined by R8. Only the
# reflection/manifest entry points have stable names in a production APK.


def verify(apk):
    classes = set()
    with zipfile.ZipFile(apk) as archive:
        for name in archive.namelist():
            if re.fullmatch(r'classes(?:[2-9]|[1-9][0-9]+)?\.dex', name):
                classes.update(dex_classes(archive.read(name)))
    missing = sorted(REQUIRED - classes)
    return dict(passed=not missing, apk=str(apk),
                apk_sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),
                missing_classes=missing, runtime_verified=False,
                scope='packaged desktop class definitions only; not UI or display policy acceptance')


def verify_menu(overlay, aapt):
    with zipfile.ZipFile(overlay) as archive:
        paths = sorted(name for name in archive.namelist() if re.fullmatch(
            r'res/xml(?:-[^/]+)?/system_dashboard_fragment(?:_desktop)?\.xml', name))
    if not paths:
        raise ValueError('No packaged system dashboard XML found')
    missing = []
    for path in paths:
        proc = subprocess.run([str(aapt), 'dump', 'xmltree', str(overlay),
                               '--file', path], capture_output=True, text=True, check=True)
        if ('sheng_desktop_mode' not in proc.stdout or
                'com.android.settings.sheng.DesktopModeSettings' not in proc.stdout):
            missing.append(path)
    return dict(passed=not missing, checked_xml=paths, missing_desktop_entry=missing,
                scope='packaged menu declarations only; not runtime visibility')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apk', type=Path)
    parser.add_argument('--overlay', type=Path)
    parser.add_argument('--aapt2', type=Path)
    args = parser.parse_args()
    if bool(args.overlay) != bool(args.aapt2):
        parser.error('--overlay and --aapt2 must be supplied together')
    result = verify(args.apk)
    if args.overlay:
        result['menu'] = verify_menu(args.overlay, args.aapt2)
        result['passed'] = result['passed'] and result['menu']['passed']
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
