#!/usr/bin/env python3
"""Add the accepted Recovery touch inputs to an existing local build mirror.

Fresh checkouts use the normal extract-files.py path. This scoped migration
uses that same generator but preserves unrelated existing vendor declarations.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


SOURCE = Path(__file__).resolve().parents[1]
GENERATED = ('Android.bp', 'Android.mk', 'BoardConfigVendor.mk', 'sheng-vendor.mk')
LIBRARIES = ('libtouchsensor', 'libtensorflowlite_touch_c')
FILEGROUPS = ('sheng_recovery_touch_executable', 'sheng_recovery_touchsensor_blob',
              'sheng_recovery_tensorflowlite_touch_blob')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def block(text, name):
    matches = list(re.finditer(r'^\w+ \{\n    name: "' + re.escape(name)
                              + r'",\n.*?^\}\n', text, re.M | re.S))
    assert len(matches) == 1, f'Expected one generated module: {name}'
    return matches[0].group()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--stock-root', type=Path, required=True,
                        help='Read-only extracted partition root containing odm/')
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    rom = args.rom.resolve(strict=True)
    vendor = rom / 'vendor/xiaomi/sheng'
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    inventory = json.loads((SOURCE / 'rootdir/recovery/touch-inputs.json').read_text())
    # Validate every source before adding any missing blob. Never overwrite a
    # different existing binary in the build tree or alter the stock extraction.
    for entry in inventory['entries']:
        original = args.stock_root / entry['source']
        target = vendor / 'proprietary' / entry['source']
        assert digest(original) == entry['sha256'], entry['source']
        assert not target.is_symlink(), f'Unexpected blob symlink: {target}'
        if target.exists():
            assert digest(target) == entry['sha256'], f'Different existing blob: {target}'
    added = []
    for entry in inventory['entries']:
        target = vendor / 'proprietary' / entry['source']
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(args.stock_root / entry['source'], target)
            added.append(entry['source'])

    subprocess.run([sys.executable, str(SOURCE / 'tools/prepare_sheng_pen_settings_product.py'),
                    '--rom', str(rom), '--work', str(work / 'source-sync'), '--include-recovery'],
                   check=True)
    before = {}
    backup = work / 'generated-before'
    backup.mkdir()
    for name in GENERATED:
        before[name] = (vendor / name).read_bytes()
        shutil.copy2(vendor / name, backup / name)
    generated = {}
    try:
        result = subprocess.run([sys.executable, 'device/xiaomi/sheng/setup-makefiles.py'],
                                cwd=rom, text=True, capture_output=True)
        (work / 'generation.log').write_text(result.stdout + result.stderr)
        assert result.returncode == 0, 'Standard vendor generation failed; see generation.log'
        for name in GENERATED:
            generated[name] = (vendor / name).read_bytes()
            (work / (name + '.generated')).write_bytes(generated[name])
    finally:
        for name in GENERATED:
            shutil.copy2(backup / name, vendor / name)

    # Take only the standard generator's raw filegroups. Its ordinary library
    # declarations must match the existing modules exactly.
    # In particular, do not normalize the existing QTI candidate dependency list.
    old = before['Android.bp'].decode()
    fresh = generated['Android.bp'].decode()
    updated = old
    for name in LIBRARIES:
        assert block(old, name) == block(fresh, name), name
    for filegroup in FILEGROUPS:
        group = block(fresh, filegroup)
        if f'    name: "{filegroup}",' in updated:
            assert block(updated, filegroup) == group
        else:
            updated = updated.rstrip('\n') + '\n\n' + group
    assert '"proprietary/odm/bin/touch_report_debug"' in block(updated, FILEGROUPS[0])
    if updated != old:
        (vendor / 'Android.bp').write_text(updated)
    for name in GENERATED[1:]:
        assert (vendor / name).read_bytes() == before[name]
    for entry in inventory['entries']:
        assert digest(vendor / 'proprietary' / entry['source']) == entry['sha256']
    report = dict(passed=True, work=str(work), added_blobs=added,
                  unchanged_blob_bytes=True, generator='standard setup-makefiles.py',
                  updated_generated_modules=list(FILEGROUPS),
                  original_vendor_libraries_unchanged=True,
                  other_generated_declarations_preserved=True,
                  before_android_bp_sha256=hashlib.sha256(before['Android.bp']).hexdigest(),
                  after_android_bp_sha256=digest(vendor / 'Android.bp'))
    (work / 'preparation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
