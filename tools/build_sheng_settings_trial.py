#!/usr/bin/env python3
"""Build a selected sheng trial module group; never install or flash."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--scope', choices=('settings', 'audio'), default='settings')
    args = parser.parse_args()
    root = args.root.resolve()
    out = root / 'out-sheng-full-clean-20261122'
    if not (out / 'combined-custom_sheng.ninja').is_file():
        parser.error('Existing sheng graph required; no graph regeneration is performed.')
    if str(root).startswith('/mnt/'):
        parser.error('Use the native C-backed WSL source tree.')
    with (out / '.sheng-device-modules.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Even read-only ninja -t queries parse this enormous graph. Do not run
        # another graph reader alongside the build: two readers caused an OOM.
        for entry in Path('/proc').iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                if (entry / 'comm').read_text().strip() in ('ninja', 'soong_build'):
                    raise RuntimeError('Another Ninja/Soong process is live; refusing concurrency.')
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                pass
        if shutil.disk_usage('/mnt/c').free < 40 * 1024**3:
            raise RuntimeError('C: has less than 40 GiB free.')
        directory = Path(tempfile.mkdtemp(prefix=f'{args.scope}-trial-serial-',
                                          dir=root.parent / 'diagnostics'))
        if args.scope == 'settings':
            targets = [out / 'target/product/sheng/system_ext/priv-app/Settings/Settings.apk',
                       out / 'target/product/sheng/odm/overlay/SettingsResOverlaySheng.apk']
        else:
            targets = [out / 'target/product/sheng/vendor/lib64/libar-pal.so']
        command = [str(root / 'prebuilts/build-tools/linux-x86/bin/ninja'), '-j1',
                   '-f', str(out / 'combined-custom_sheng.ninja'), *map(str, targets)]
        # Graph output names are relative, not aliases for absolute paths.
        command[-len(targets):] = [str(p.relative_to(root)) for p in targets]
        # sdkparcelables contains Java 21 bytecode. A direct Ninja invocation
        # does not inherit envsetup's JDK selection; host Java 11 fails here.
        java_home = root / 'prebuilts/jdk/jdk21/linux-x86'
        if not (java_home / 'bin/java').is_file():
            raise RuntimeError('Bundled JDK 21 is required for sdkparcelables.')
        environment = os.environ.copy()
        environment['JAVA_HOME'] = str(java_home)
        environment['PATH'] = str(java_home / 'bin') + os.pathsep + environment.get('PATH', '')
        receipt = {'scope': args.scope, 'argv': command,
                   'java_home': str(java_home),
                   'installed': False, 'flashed': False, 'slot_changed': False}
        with (directory / 'build.log').open('w') as log:
            process = subprocess.Popen(command, cwd=root, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True,
                                       env=environment)
            receipt['pid'] = process.pid
            (directory / 'process.json').write_text(json.dumps(receipt, indent=2))
            print(directory, flush=True)
            while process.poll() is None:
                if shutil.disk_usage('/mnt/c').free < 40 * 1024**3:
                    receipt['stop_reason'] = 'C: free space below 40 GiB'
                    os.killpg(process.pid, signal.SIGINT)
                    break
                time.sleep(5)
            receipt['returncode'] = process.wait()
        (directory / 'result.json').write_text(json.dumps(receipt, indent=2))
        print(json.dumps(receipt), flush=True)
        return 0 if receipt['returncode'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
