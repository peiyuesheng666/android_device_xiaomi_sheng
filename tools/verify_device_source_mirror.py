#!/usr/bin/env python3
"""Reject a build mirror that differs from an authoritative device source tree."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


DEVICE = Path('device/xiaomi/sheng')
# Documentation and local build caches are not Android build inputs.
BUILD_DIRS = {'aidl', 'configs', 'dolby', 'interfaces', 'overlay', 'properties',
              'rootdir', 'sepolicy'}


def digest(path):
    if path.is_symlink():
        return {'kind': 'symlink', 'target': str(path.readlink())}
    if not path.is_file():
        return {'kind': 'missing'}
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(block)
    return {'kind': 'file', 'sha256': hasher.hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--path', action='append', default=[],
                        help='Device-relative input subtree for a scoped build; default: all inputs')
    parser.add_argument('--reject-extra', action='store_true',
                        help='Also reject unexpected mirror files within explicit directory scopes')
    args = parser.parse_args()
    workspace, rom = args.workspace.resolve(strict=True), args.rom.resolve(strict=True)
    scopes = [Path(value) for value in args.path]
    if any(path.is_absolute() or '..' in path.parts for path in scopes):
        parser.error('--path must stay relative to device/xiaomi/sheng')
    if args.reject_extra and not scopes:
        parser.error('--reject-extra requires explicit source scopes')
    names = subprocess.check_output([
        'git', '-C', str(workspace), 'ls-files', '-z', '--cached', '--others',
        '--exclude-standard', '--', DEVICE.as_posix()]).decode('utf-8').split('\0')
    inputs = {}
    mismatches = []
    for name in sorted(set(filter(None, names))):
        relative = Path(name).relative_to(DEVICE)
        if scopes and not any(relative == path or path in relative.parents for path in scopes):
            continue
        if len(relative.parts) == 1 and relative.suffix.lower() not in {'.bp', '.mk', '.py', '.txt', '.sh'}:
            continue
        if len(relative.parts) > 1 and relative.parts[0] not in BUILD_DIRS:
            continue
        expected, actual = digest(workspace / name), digest(rom / name)
        inputs[name] = expected
        if expected != actual or expected['kind'] == 'missing':
            mismatches.append({'path': name, 'workspace': expected, 'rom': actual})
    unexpected = []
    generated_inputs = {}
    ignored_bytecode = []
    if args.reject_extra:
        for scope in scopes:
            mirror_scope = rom / DEVICE / scope
            if not mirror_scope.is_dir():
                continue
            for path in sorted(mirror_scope.rglob('*')):
                if not (path.is_file() or path.is_symlink()):
                    continue
                name = str(path.relative_to(rom)).replace('\\', '/')
                if name not in inputs:
                    if '__pycache__' in path.parts and path.suffix == '.pyc':
                        ignored_bytecode.append(name)
                        continue
                    original = workspace / name
                    if original.is_file() or original.is_symlink():
                        # Generated models and SDK inputs can be gitignored but
                        # remain real build inputs. Compare them instead of
                        # dropping them from a strict source-mirror check.
                        expected, actual = digest(original), digest(path)
                        generated_inputs[name] = expected
                        if expected != actual or expected['kind'] == 'missing':
                            mismatches.append({'path': name, 'workspace': expected,
                                               'rom': actual, 'reason': 'generated input differs'})
                    else:
                        unexpected.append(name)
        for name in sorted(set(unexpected)):
            mismatches.append({'path': name, 'workspace': {'kind': 'missing'},
                               'rom': digest(rom / name), 'reason': 'unexpected mirror input'})
    if not inputs:
        raise RuntimeError('No device build inputs found in the workspace Git inventory')
    report = dict(date_utc=datetime.now(timezone.utc).isoformat(),
                  workspace=str(workspace), rom=str(rom), inputs=inputs,
                  scopes=[path.as_posix() for path in scopes],
                  generated_inputs=generated_inputs,
                  ignored_python_bytecode=sorted(set(ignored_bytecode)),
                  unexpected_mirror_inputs=sorted(set(unexpected)),
                  mismatches=mismatches, passed=not mismatches)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f'Device source mirror: {len(inputs)} inputs, {len(mismatches)} mismatches')
    for entry in mismatches:
        print(entry['path'])
    if mismatches:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
