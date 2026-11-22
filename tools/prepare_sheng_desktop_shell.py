#!/usr/bin/env python3
"""Apply the device-owned desktop policy patch to its pinned Shell sources."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def prepare(rom, patch, check_only=False):
    data = patch.read_bytes().replace(b'\r\n', b'\n')
    paths = [line[6:] for line in data.decode().splitlines() if line.startswith('+++ b/')]
    assert paths and all(p.startswith('frameworks/base/libs/WindowManager/Shell/src/')
                         and '..' not in Path(p).parts for p in paths)
    def run(*args):
        return subprocess.run(['patch', '--fuzz=0', '--no-backup-if-mismatch', '-p1', *args], cwd=rom,
                              input=data, capture_output=True)
    forward = run('--batch', '--dry-run', '--forward')
    if forward.returncode == 0:
        if not check_only:
            result = run('--batch', '--forward')
            assert result.returncode == 0, result.stderr.decode(errors='replace')
        state = 'applicable' if check_only else 'applied'
    else:
        reverse = run('--force', '--dry-run', '--reverse')
        assert reverse.returncode == 0, ('Shell source differs from the pinned patch; no changes applied.\n'
                                         + forward.stdout.decode(errors='replace'))
        state = 'already_applied'
    return {'state': state, 'files': [
        {'path': p, 'sha256': hashlib.sha256((rom / p).read_bytes()).hexdigest()}
        for p in paths]}


def prepare_policies(rom, source):
    patches = [source / name for name in
               ('shell-policy.patch', 'display-mode-policy.patch', 'home-transition.patch')]
    upgrade = source / 'keyboard-auto-policy.patch'
    if upgrade.exists():
        patches.append(upgrade)
    paths = set()
    for patch in patches:
        for line in patch.read_text().splitlines():
            if line.startswith('+++ b/'):
                relative = Path(line[6:])
                assert relative.as_posix().startswith('frameworks/base/libs/WindowManager/Shell/src/')
                assert '..' not in relative.parts
                paths.add(relative)
    # Sequential preflight in a disposable copy handles overlapping hunks without
    # partially installing policies if a later patch conflicts.
    with tempfile.TemporaryDirectory(prefix='sheng-desktop-preflight-') as directory:
        stage = Path(directory)
        original = {path: (rom / path).read_bytes() for path in paths}
        for path, content in original.items():
            target = stage / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        if upgrade.exists():
            # A previously prepared tree may already contain the keyboard upgrade.
            # Reconstruct the original policy in the temporary copy only.
            command = ['patch', '--force', '--fuzz=0', '--reverse', '-p1']
            data = upgrade.read_bytes().replace(b'\r\n', b'\n')
            if subprocess.run(command + ['--dry-run'], cwd=stage, input=data,
                              capture_output=True).returncode == 0:
                subprocess.run(command, cwd=stage, input=data, capture_output=True, check=True)
        results = [prepare(stage, patch) for patch in patches]
        changed = {path: (stage / path).read_bytes() for path in paths
                   if (stage / path).read_bytes() != original[path]}
        assert all((rom / path).read_bytes() == content for path, content in original.items()), (
            'Shell inputs changed during staging; no changes applied')
        for path, content in changed.items():
            (rom / path).write_bytes(content)
    result = results[0]
    result['state'] = 'applied' if changed else 'already_applied'
    result['display_mode'], result['home_transition'] = results[1:3]
    if upgrade.exists():
        result['keyboard_auto'] = results[3]
    for entry in result['files'] + result['display_mode']['files']:
        entry['sha256'] = hashlib.sha256((rom / entry['path']).read_bytes()).hexdigest()
    return result



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / 'interfaces/display/desktop'
    result = prepare_policies(args.rom.resolve(), source)
    for original in (source / 'shellsrc').rglob('*.java'):
        relative = original.relative_to(source / 'shellsrc')
        target = args.rom.resolve() / 'frameworks/base/libs/WindowManager/Shell/src' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        result['files'].append({'path': str(target.relative_to(args.rom.resolve())),
                                'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
