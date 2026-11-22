#!/usr/bin/env python3
"""Synchronize only reviewed batch inputs; retain the deferred face source."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

SCOPES = ['BoardConfig.mk', 'device.mk', 'configs/audio/sku_kalama', 'properties/vendor.prop',
          'interfaces/display/defaults', 'overlay/FrameworkResOverlaySheng',
          'overlay/LineageResOverlaySheng', 'interfaces/input/touch',
          'sepolicy/vendor/genfs_contexts', 'sepolicy/vendor/file_contexts']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    args.work.mkdir(exist_ok=False)
    source = args.workspace / 'device/xiaomi/sheng'
    target = args.rom / 'device/xiaomi/sheng'
    receipts = {}
    for scope in SCOPES + ['tools/build_hardware.sh', 'tools/verify_device_source_mirror.py']:
        item = source / scope
        paths = sorted(item.rglob('*')) if item.is_dir() else [item]
        for path in paths:
            if not path.is_file() or '__pycache__' in path.parts:
                continue
            relative = path.relative_to(source)
            dest = target / relative
            backup = args.work / 'source-backup' / relative
            if dest.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, backup)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            receipts[str(relative)] = hashlib.sha256(dest.read_bytes()).hexdigest()
    # r46 only added a face key namespace to the already built r44 policy.
    # Compile from its original device source with that deferred addition absent.
    # Keep the Windows candidate and a backup untouched; never edit compiled CIL.
    face = target / 'sepolicy/system_ext/private/sheng_face.te'
    text = face.read_text()
    start = text.index('# Hardware encryption keys have a dedicated SELinux namespace')
    end = text.index('allow sheng_face { app_api_service', start)
    backup = args.work / 'deferred-face-source/sheng_face.te'
    backup.parent.mkdir(parents=True)
    shutil.copy2(face, backup)
    face.write_text(text[:start] + text[end:])
    keys = target / 'sepolicy/system_ext/private/keystore2_key_contexts'
    assert '10001 u:object_r:sheng_face_key:s0' in keys.read_text()
    shutil.move(keys, backup.parent / keys.name)
    (args.work / 'source-sync.json').write_text(json.dumps(dict(
        scopes=SCOPES, sha256=receipts,
        deferred_face_source_backup=str(backup.parent),
        build_face_policy='r44 source, without deferred r46 key namespace'), indent=2) + '\n')


if __name__ == '__main__':
    main()
