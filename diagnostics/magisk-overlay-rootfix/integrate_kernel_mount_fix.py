#!/usr/bin/env python3
"""Integrate the qualified mount-source fix into sheng's source kernel package.

Explicit --apply only. Extends (never disables) all original source contracts,
updates the complete source manifest, and preserves before-images in a report.
No build output, public Android repository or device partition is modified.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from storage_guard import require_build_space

HERE = Path(__file__).resolve().parent
CONTRACT_BASE = '463d52346a3f60d76cb9c2492807ce89adb0377d5e161dd029bd3fd867effc3f'
RELATIVE_SOURCE = 'k618/ws/common/fs/namespace.c'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, indent=2) + '\n').encode()


def extend_contract(original, receipt_sha256):
    if sha(original) != CONTRACT_BASE:
        raise ValueError('Unknown kernel provenance checker; review before integrating')
    marker = b'    for name,item in expected.items():\n'
    if original.count(marker) != 1:
        raise ValueError('Ambiguous source-contract insertion')
    addition = f'''    mount_fix=project/'provenance/magisk-mount-source-root.json'
    assert hashlib.sha256(mount_fix.read_bytes()).hexdigest()=='{receipt_sha256}'
    fix=json.loads(mount_fix.read_text())
    assert hashlib.sha256((project/fix['patch']).read_bytes()).hexdigest()==fix['patch_sha256']
    for name,item in fix['files'].items():
        assert name in expected and expected[name]['after']==item['before'], name
        expected[name]=item
'''.encode()
    return original.replace(marker, addition + marker)


def updated_manifest(original, before, after):
    manifest = json.loads(original)
    entry = manifest[RELATIVE_SOURCE]
    if entry != dict(sha256=sha(before), bytes=len(before)):
        raise ValueError('Source manifest does not match pinned original')
    manifest[RELATIVE_SOURCE] = dict(sha256=sha(after), bytes=len(after))
    result = encode(manifest)
    # Preserve every other source entry, including symlinks and byte counts.
    old = json.loads(original)
    changed = [name for name in manifest if manifest[name] != old[name]]
    if changed != [RELATIVE_SOURCE] or manifest.keys() != old.keys():
        raise ValueError('Unexpected source inventory change')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    rom = args.rom.resolve(strict=True)
    project = (rom / 'kernel/xiaomi/sheng-build').resolve(strict=True)
    source = project / 'sources' / RELATIVE_SOURCE
    assert (rom / 'kernel/xiaomi/sheng').resolve() == source.parents[1]
    base = json.loads((HERE / 'candidate-base.json').read_text())
    before = source.read_bytes()
    assert sha(before) == base['kernel_base_sha256']
    patch = (HERE / 'kernel-avoid-unused-source-root-mountpoint.patch').read_bytes()
    with tempfile.TemporaryDirectory(prefix='sheng-kernel-mount-fix-') as temp:
        original = Path(temp) / 'namespace.c'
        original.write_bytes(before)
        patch_path = Path(temp) / 'fix.patch'
        patch_path.write_bytes(patch)
        subprocess.run(['patch', '--batch', '--fuzz=0', str(original), str(patch_path)],
                       check=True, capture_output=True)
        after = original.read_bytes()
    assert sha(after) == base['kernel_candidate_sha256']
    patch_relative = 'patches/sheng-magisk-mount-source-root.patch'
    provenance = dict(schema=1, purpose='Preserve deleted-source bind moves without changing mount security checks',
                      patch=patch_relative, patch_sha256=sha(patch),
                      files={RELATIVE_SOURCE: dict(before=sha(before), after=sha(after))},
                      android_runtime_verified=False, full_source_build_verified=False)
    provenance_bytes = encode(provenance)
    old_contract = (project / 'scripts/android_lts_contract.py').read_bytes()
    new_contract = extend_contract(old_contract, sha(provenance_bytes))
    old_manifest = (project / 'SOURCE-SHA256.json').read_bytes()
    new_manifest = updated_manifest(old_manifest, before, after)
    old_metadata = (project / 'SOURCE.json').read_bytes()
    metadata = json.loads(old_metadata)
    assert metadata['source_manifest_sha256'] == sha(old_manifest)
    metadata['source_manifest_sha256'] = sha(new_manifest)
    metadata['source_changes_since_validated_image'] = ['provenance/magisk-mount-source-root.json']
    metadata['current_source_full_build_verified'] = False
    changes = {
        source: after,
        project / patch_relative: patch,
        project / 'provenance/magisk-mount-source-root.json': provenance_bytes,
        project / 'scripts/android_lts_contract.py': new_contract,
        project / 'SOURCE-SHA256.json': new_manifest,
        project / 'SOURCE.json': encode(metadata),
    }
    assert not (project / patch_relative).exists()
    assert not (project / 'provenance/magisk-mount-source-root.json').exists()
    print(json.dumps(dict(apply=args.apply, changed_paths=[str(p) for p in changes],
                          source_before=sha(before), source_after=sha(after)), indent=2), flush=True)
    if not args.apply:
        return
    report = args.report.resolve()
    assert not report.exists()
    require_build_space(report, minimum_host=6 * 1024**3)
    require_build_space(project, minimum_host=6 * 1024**3)
    with (rom / 'out-clean-ota-20261116/.sheng-device-modules.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        active = subprocess.check_output(['ps', '-eo', 'comm='], text=True).splitlines()
        assert not any(x.strip() in ('soong_build', 'ninja', 'clang', 'clang++') for x in active)
        report.mkdir(parents=True)
        rows = {}
        originals = {}
        for path, data in changes.items():
            relative = str(path.relative_to(project))
            original = path.read_bytes() if path.exists() else None
            originals[path] = original
            if original is not None:
                backup = report / 'before' / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(original)
            rows[relative] = dict(before=None if original is None else sha(original), after=sha(data))
        receipt = dict(passed=False, source_integrated=False, files=rows,
                       public_android_sources_modified=False, build_outputs_modified=False,
                       compiled=False, android_runtime_verified=False, device_access=False, flashed=False)
        receipt_path = report / 'qualification.json'
        receipt_path.write_bytes(encode(receipt))
        for path, data in changes.items():
            assert (path.read_bytes() if path.exists() else None) == originals[path], 'Concurrent source change'
            stage = path.with_name(path.name + '.sheng-magisk-rootfix.tmp')
            with stage.open('xb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if path.exists():
                stage.chmod(path.stat().st_mode & 0o777)
            os.replace(stage, path)
        environment = dict(os.environ, PROJECT_ROOT=str(project), BUILD_ROOT=str(project / 'sources'))
        p = subprocess.run(['python3', str(project / 'scripts/android_lts_contract.py')],
                           env=environment, capture_output=True)
        (report / 'source-contract.stdout').write_bytes(p.stdout)
        (report / 'source-contract.stderr').write_bytes(p.stderr)
        assert all(sha(path.read_bytes()) == sha(data) for path, data in changes.items())
        receipt.update(source_integrated=True, source_contract_returncode=p.returncode,
                       passed=p.returncode == 0, full_source_build_verified=False)
        receipt_path.write_bytes(encode(receipt))
        p.check_returncode()
        print(p.stdout.decode(), flush=True)


if __name__ == '__main__':
    main()
