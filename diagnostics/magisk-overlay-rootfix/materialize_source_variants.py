#!/usr/bin/env python3
"""Materialize pinned sheng-only init/fs_mgr copies; never patch public sources.

The lock is reviewed source, not regenerated automatically. A changed upstream,
patch, or edited local copy fails closed. --verify-only never writes source.
Blueprints retain upstream defaults; only the first-stage fs_mgr dependency and
its child-mount preservation implementation differ. No build or device access.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess
import tempfile

from storage_guard import require_build_space

HERE = Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def safe_relative(text):
    path = Path(text)
    if not path.parts or path.is_absolute() or '..' in path.parts or '\\' in text or ':' in text:
        raise ValueError('Unsafe locked path: ' + text)
    return path


def checked_copy(data, expected, name):
    if sha(data) != expected:
        raise ValueError('Pinned source identity mismatch: ' + name)
    return data


def transform_crypto_defaults(data, kind):
    """Copy private defaults with module identifiers renamed, never relax visibility."""
    text = data.decode('utf-8')
    if kind == 'crypto-main-defaults':
        names = ('boringssl_flags_common', 'boringssl_flags',
                 'boringssl_defaults', 'libcrypto_defaults')
        selected = []
        for name in names:
            matches = [block for block in re.findall(r'(?ms)^cc_defaults \{.*?^\}', text)
                       if re.search(r'\bname:\s*"' + re.escape(name) + '"', block)]
            assert len(matches) == 1, 'Ambiguous pinned crypto defaults: ' + name
            selected.append(matches[0])
        text = '\n\n'.join(selected) + '\n'
    elif kind == 'crypto-generated-defaults':
        names = re.findall(r'\bname:\s*"([^"]+)"', text)
        assert names and len(names) == len(set(names))
    elif kind == 'unwind-private-header-defaults':
        variables = re.findall(r'(?ms)^libunwindstack_common_src_files = \[.*?^\]', text)
        blocks = [block for block in re.findall(r'(?ms)^cc_defaults \{.*?^\}', text)
                  if 'name: "libunwindstack_defaults"' in block]
        assert len(variables) == 1 and len(blocks) == 1
        text = variables[0] + '\n\n' + blocks[0] + '\n'
        text = text.replace('"bionic_libc_platform_headers"',
                            '"libsheng_bionic_platform_headers"')
        text = text.replace('"libzstd"', '"libsheng_zstd_first_stage"')
        names = ('libunwindstack_defaults',)
    else:
        raise ValueError('Unknown locked source transform: ' + kind)
    for name in names:
        text = text.replace('"' + name + '"', '"sheng_first_stage_' + name + '"')
    return text.encode('utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--device', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--check-only', action='store_true',
                        help='Read-only build gate; emit one success token, no report')
    args = parser.parse_args()
    rom, device = args.rom.resolve(strict=True), args.device.resolve(strict=True)
    if args.check_only:
        assert args.report is None, 'Check-only must not create a report'
        args.verify_only = True
    else:
        assert args.report is not None, 'A report is required outside check-only mode'
    report = args.report.resolve() if args.report else None
    assert report is None or not report.exists(), 'Preserve earlier receipts'
    lock_path = HERE / 'source-variants-lock.json'
    lock_bytes = lock_path.read_bytes()
    lock = json.loads(lock_bytes)
    assert lock['schema'] == 1
    patch = HERE / 'fs_mgr-preserve-file-submounts.patch'
    patch_bytes = checked_copy(patch.read_bytes(), lock['patch_sha256'], 'fs_mgr patch')
    planned, originals, rows = {}, {}, {}
    for relative, row in lock['sources'].items():
        path = rom / safe_relative(relative)
        data = checked_copy(path.read_bytes(), row['sha256'], relative)
        originals[path] = row['sha256']
        if row.get('destination') is None:
            continue
        target = device / safe_relative(row['destination'])
        if not target.resolve().is_relative_to(device):
            raise ValueError('Destination escapes device source: ' + str(target))
        if row.get('patched'):
            with tempfile.TemporaryDirectory(prefix='sheng-owned-fsmgr-') as temp:
                source = Path(temp) / 'fs_mgr_overlayfs_mount.cpp'
                source.write_bytes(data)
                patch_copy = Path(temp) / 'fix.patch'
                patch_copy.write_bytes(patch_bytes)
                subprocess.run(['patch', '--batch', '--fuzz=0', str(source), str(patch_copy)],
                               check=True, capture_output=True)
                data = source.read_bytes()
        if row.get('transform'):
            data = transform_crypto_defaults(data, row['transform'])
        checked_copy(data, row['output_sha256'], row['destination'])
        assert target not in planned, 'Duplicate destination'
        planned[target] = data
        rows[row['destination']] = dict(upstream=relative, before=row['sha256'],
                                        output_sha256=sha(data), patched=bool(row.get('patched')),
                                        transform=row.get('transform'))
    # Validate every input and local destination before writing any source.
    for target, data in planned.items():
        if target.is_symlink():
            raise ValueError('Refuse source symlink: ' + str(target))
        if target.exists():
            checked_copy(target.read_bytes(), sha(data), str(target))
        elif args.verify_only:
            raise ValueError('Missing device-owned source: ' + str(target))
    if report is not None:
        require_build_space(report, minimum_output=32 * 1024**2)
    if not args.verify_only:
        require_build_space(device, minimum_output=32 * 1024**2)
        for target, data in planned.items():
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as stream:
                    stream.write(data)
    assert all(sha(path.read_bytes()) == expected for path, expected in originals.items())
    assert all(sha(target.read_bytes()) == sha(data) for target, data in planned.items())
    if args.check_only:
        print('SHENG_SOURCE_VARIANTS_VERIFIED')
        return
    report.mkdir(parents=True)
    receipt = dict(passed=True, lock_sha256=sha(lock_bytes), files=rows,
                   pinned_input_count=len(originals), materialized_file_count=len(planned),
                   patched_file_count=sum(row['patched'] for row in rows.values()),
                   transformed_file_count=sum(bool(row['transform']) for row in rows.values()),
                   verify_only=args.verify_only, public_sources_unchanged=True,
                   product_graph_verified=False, product_install_verified=False,
                   compiled=False, device_access=False, flashed=False)
    (report / 'qualification.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({key: value for key, value in receipt.items() if key != 'files'}, indent=2))


if __name__ == '__main__':
    main()
