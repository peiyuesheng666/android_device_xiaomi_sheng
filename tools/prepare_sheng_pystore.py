#!/usr/bin/env python3
"""Integrate device-owned boot-only pystore into the native-layout kernel tree.

No device access, build output edits or claims of linked/runtime qualification.
Dry-run by default. Reject unknown logger changes; preserve source manifests.
"""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import subprocess

LOGGER = 'k618/ws/common/drivers/misc/sheng_bootlog.c'
KNOWN_LOGGER = '5ad45dd4844a65ee1f2e85a5b1400495d52a302a51a58bff142575e8bc25911f'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, indent=2) + '\n').encode()


def config(data):
    lines = data.decode().splitlines()
    for key, value in [('CONFIG_SHENG_BOOTLOG', 'y'), ('CONFIG_LOG_BUF_SHIFT', '22')]:
        lines = [line for line in lines if not line.startswith(key + '=') and
                 line != '# ' + key + ' is not set']
        lines.append(key + '=' + value)
    return ('\n'.join(lines) + '\n').encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = args.project.resolve(strict=True)
    owned = Path(__file__).resolve().parents[1] / 'interfaces/kernel/6.18'
    native = json.loads((root / 'provenance/native-layout-restoration.json').read_text())
    for name, row in native['files'].items():
        if digest((root / 'sources' / name).read_bytes()) != row['after']:
            raise ValueError('Not the qualified native layout: ' + name)
    manifest = json.loads((root / 'SOURCE-SHA256.json').read_text())
    before = (root / 'sources' / LOGGER).read_bytes()
    after = (owned / 'sheng_bootlog.c').read_bytes()
    if manifest[LOGGER] != dict(sha256=digest(before), bytes=len(before)):
        raise ValueError('Logger differs from source manifest')
    if digest(before) not in (KNOWN_LOGGER, digest(after)):
        raise ValueError('Unknown logger implementation; review before replacing')
    changes = {'sources/' + LOGGER: after}
    provenance_name = 'provenance/pystore-boot-only.json'
    patch_name = 'patches/pystore-boot-only.patch'
    contract_name = 'scripts/android_lts_contract.py'
    if digest(before) == digest(after):
        receipt = (root / provenance_name).read_bytes()
        record = json.loads(receipt)
        if record['files'][LOGGER]['after'] != digest(after):
            raise ValueError('Existing pystore provenance does not match owned source')
    else:
        patch = ''.join(difflib.unified_diff(before.decode().splitlines(True),
                       after.decode().splitlines(True), fromfile='a/' + LOGGER,
                       tofile='b/' + LOGGER)).encode()
        receipt = encode(dict(patch=patch_name, patch_sha256=digest(patch),
                         files={LOGGER: dict(before=digest(before), after=digest(after))},
                         linked_verified=False, runtime_verified=False))
        changes[patch_name] = patch
        changes[provenance_name] = receipt
    contract = (root / contract_name).read_text()
    if "project/'provenance/pystore-boot-only.json'" not in contract:
        marker = '    for name,item in expected.items():\n'
        if contract.count(marker) != 1:
            raise ValueError('Unknown source-contract insertion point')
        extension = f'''    pystore_path=project/'provenance/pystore-boot-only.json'
    assert hashlib.sha256(pystore_path.read_bytes()).hexdigest()=='{digest(receipt)}'
    pystore=json.loads(pystore_path.read_text())
    assert hashlib.sha256((project/pystore['patch']).read_bytes()).hexdigest()==pystore['patch_sha256']
    for name,item in pystore['files'].items():
        assert name in expected and expected[name]['after']==item['before'], name
        expected[name]=item
'''
        changes[contract_name] = contract.replace(marker, extension + marker).encode()
    for name in ['sheng_defconfig', 'sources/k618/ws/common/arch/arm64/configs/sheng_defconfig']:
        changes[name] = config((root / name).read_bytes())
    manifest[LOGGER] = dict(sha256=digest(after), bytes=len(after))
    changes['SOURCE-SHA256.json'] = encode(manifest)
    metadata = json.loads((root / 'SOURCE.json').read_text())
    metadata.update(source_manifest_sha256=digest(changes['SOURCE-SHA256.json']),
                    pystore_source_sha256=digest(after), pystore_provenance=provenance_name,
                    current_source_full_build_verified=False,
                    validated_image_sha256=None, runtime_verified=False,
                    matching_module_rebuild_required=True)
    changes['SOURCE.json'] = encode(metadata)
    changed = [name for name, data in changes.items()
               if not (root / name).exists() or (root / name).read_bytes() != data]
    if args.apply:
        original = {name: (root / name).read_bytes() if (root / name).exists() else None
                    for name in changed}
        try:
            for name in changed:
                (root / name).write_bytes(changes[name])
            env = dict(os.environ, PROJECT_ROOT=str(root), BUILD_ROOT=str(root / 'sources'))
            subprocess.run(['python3', str(root / 'scripts/android_lts_contract.py')],
                           env=env, check=True, timeout=120)
        except BaseException:
            for name, data in original.items():
                if data is None:
                    (root / name).unlink(missing_ok=True)
                else:
                    (root / name).write_bytes(data)
            raise
    print(json.dumps(dict(applied=args.apply, project=str(root), changed=changed,
                          logger_sha256=digest(after), linked_verified=False,
                          runtime_verified=False, flashed=False), indent=2))


if __name__ == '__main__':
    main()
