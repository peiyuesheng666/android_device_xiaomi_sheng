#!/usr/bin/env python3
"""Export audited current init/remounter bytes for offline image integration.

This does not qualify kernel/modules, images, AVB, policy or Android runtime.
No device access, source mutation or build is performed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[4]


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''):
            digest.update(chunk)
    return digest.hexdigest()


def regular_under(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Expected a build-root-relative file')
    path = root / relative
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected a regular compiled file')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Compiled file escapes build root')
    return path


def check_static_elf(data):
    if len(data) < 64 or data[:7] != b'\x7fELF\x02\x01\x01':
        raise ValueError('Expected ELF64 little-endian executable')
    header = struct.unpack_from('<HHIQQQIHHHHHH', data, 16)
    kind, machine, version, _, phoff, _, _, ehsize, phsize, phnum, _, _, _ = header
    if (kind, machine, version, ehsize, phsize) != (2, 183, 1, 64, 56):
        raise ValueError('Expected AArch64 ET_EXEC')
    if not phnum or phoff < 64 or phoff + phsize * phnum > len(data):
        raise ValueError('Invalid ELF program header table')
    types = [struct.unpack_from('<I', data, phoff + i * phsize)[0] for i in range(phnum)]
    if 1 not in types or 2 in types or 3 in types:
        raise ValueError('Expected static LOAD, without DYNAMIC or INTERP')


def check_binary(root, record):
    if not all(record[k] is True for k in ('identical', 'static_aarch64_exec', 'executable')):
        raise ValueError('Binary audit did not qualify all checks')
    files = record['files']
    if len(files) != 3 or len({row['path'] for row in files}) != 3:
        raise ValueError('Need distinct compiler, adapter and staging files')
    hashes = set()
    paths = []
    for row in files:
        path = regular_under(root, row['path'])
        if path.stat().st_size != row['bytes'] or sha(path) != row['sha256']:
            raise ValueError('Compiled bytes changed after audit')
        if not os.access(path, os.X_OK):
            raise ValueError('Compiled file is not executable')
        check_static_elf(path.read_bytes())
        hashes.add(row['sha256'])
        paths.append(path)
    if len(hashes) != 1:
        raise ValueError('Compiler, adapter and installed bytes differ')
    return paths[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    rom = args.rom.resolve(strict=True)
    audit_file = args.audit.resolve(strict=True) / 'qualification.json'
    build_file = args.build.resolve(strict=True) / 'qualification.json'
    audit = json.loads(audit_file.read_text())
    build = json.loads(build_file.read_text())
    if not (audit['passed'] and audit['source_gate_passed'] and audit['incremental_no_work_passed']
            and build['passed'] and build['compiled'] and build['returncode'] == 0
            and build['guard_stop'] is None and build['source_gate_after']):
        raise ValueError('Actual build/audit gates have not passed')
    no_work_file = WORKSPACE / audit['incremental_no_work_receipt']
    no_work = json.loads(no_work_file.read_text())
    if not (no_work['passed'] and no_work['final_dry_run']['no_scheduled_commands']
            and (no_work_file.parent / 'final-dry-run.stderr').read_text().strip()
            == 'ninja: no work to do.'):
        raise ValueError('Missing terminal no-work evidence')
    binaries = {name: check_binary(rom, audit['binaries'][name])
                for name in ('init', 'overlay_remounter')}
    rsp = regular_under(rom, audit['init_link_rsp']['path'])
    if sha(rsp) != audit['init_link_rsp']['sha256']:
        raise ValueError('Link response changed')
    for row in audit['archives'].values():
        archive = regular_under(rom, row['path'])
        if sha(archive) != row['sha256'] or archive.stat().st_size != row['bytes']:
            raise ValueError('Private archive changed')
        if row['path'] not in rsp.read_text():
            raise ValueError('Private archive absent from actual init link')
    if len(audit['archives']) != 5:
        raise ValueError('Incomplete private archive audit')
    sources = {}
    for name in ('overlay_remounter.cpp', 'mount_preserver.h'):
        relative = Path('device/xiaomi/sheng/interfaces/compat/overlay-remounter') / name
        if sha(WORKSPACE / relative) != sha(rom / relative):
            raise ValueError('Workspace/native remounter source differs')
        sources[name] = sha(rom / relative)
    gate = subprocess.run(['python3', str(HERE / 'materialize_source_variants.py'),
                           '--rom', str(rom), '--device', str(rom / 'device/xiaomi/sheng'),
                           '--check-only'], capture_output=True, text=True, check=True)
    if gate.stdout.strip() != 'SHENG_SOURCE_VARIANTS_VERIFIED':
        raise ValueError('Unexpected source gate response')
    out = args.out.resolve()
    if out.exists():
        raise ValueError('Preserve earlier exports; output must be new')
    out.mkdir(parents=True)
    evidence = {'audit_sha256': sha(audit_file), 'build_receipt_sha256': sha(build_file),
                'no_work_receipt_sha256': sha(no_work_file), 'source_gate': gate.stdout.strip()}
    rows = {}
    for name, binary in binaries.items():
        folder = out / ('overlay-remounter' if name == 'overlay_remounter' else 'first-stage-init')
        folder.mkdir()
        shutil.copy2(binary, folder / name)
        if sha(folder / name) != sha(binary):
            raise ValueError('Export copy differs')
        receipt = dict(passed=True, test_only=False, binary_sha256=sha(binary),
                       build_mode='actual-current-product-source', evidence=evidence,
                       runtime_verified=False, flashed=False)
        if name == 'overlay_remounter':
            receipt.update(source_sha256=sources['overlay_remounter.cpp'],
                           header_sha256=sources['mount_preserver.h'])
        (folder / 'qualification.json').write_text(json.dumps(receipt, indent=2) + '\n')
        rows[name] = dict(path=str(folder / name), sha256=sha(folder / name))
    result = dict(passed=True, scope='audited binary export only', binaries=rows,
                  evidence=evidence, images_verified=False, runtime_verified=False, flashed=False)
    (out / 'qualification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
