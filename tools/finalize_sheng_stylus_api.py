#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bring an officially frozen, normally generated V1 API into the device source."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guard', type=Path, required=True)
    args = parser.parse_args()
    device = Path(__file__).resolve().parents[1]
    workspace = device.parents[2]
    rom = Path('/root/sheng-lineage/lineage-24.0')
    mirror = rom / 'device/xiaomi/sheng'
    relative = Path('interfaces/input/stylus')
    interface = 'vendor.lineage.sheng.stylus'
    guard = json.loads(args.guard.read_text())
    assert guard['phase'] == 'freeze-api' and guard.get('phase_exit_code', guard.get('exit_code')) == 0
    assert guard['api_freeze_command_passed'] and guard['compiler_restored']
    assert guard['module_status']['modules'] == [interface + '-freeze-api']
    assert guard['module_status']['postbuild_checks_completed']
    work = Path(tempfile.mkdtemp(prefix='api-freeze-finalization-',
                                dir=workspace / 'reports/device/20261114-stylus-service'))
    receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), passed=False,
                   normal_api_freeze_command=True, api_frozen=False,
                   frozen_modules_rebuilt=False, installed=False, commands=[])
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()

    def run(command, label):
        result = subprocess.run(list(map(str, command)), cwd=rom,
                                capture_output=True, timeout=60)
        (work / (label + '.txt')).write_bytes(result.stdout + result.stderr)
        receipt['commands'].append(dict(command=list(map(str, command)), exit_code=result.returncode))
        result.check_returncode()

    try:
        with (rom / 'out/.sheng-device-modules.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            compiler = rom / 'out/host/linux-x86/bin/soong_build'
            assert not compiler.with_name(compiler.name + '.sheng-real').exists()
            assert compiler.read_bytes()[:4] == b'\x7fELF'
            processes = subprocess.check_output(['ps', '-eo', 'comm='], text=True).splitlines()
            assert not any(name.strip() in ('soong_build', 'ninja') for name in processes)
            sync = json.loads((args.guard.parent / 'stylus-source-sync.json').read_text())
            for name, record in sync['files'].items():
                if not name.startswith(str(relative) + '/'):
                    continue
                assert sha(device / name) == record['sha256'], 'Source changed since freezing: ' + name
                if name != str(relative / 'Android.bp'):
                    assert sha(mirror / name) == record['sha256'], 'Unexpected mirror change: ' + name

            blueprint = device / relative / 'Android.bp'
            frozen_blueprint = mirror / relative / 'Android.bp'
            shutil.copyfile(blueprint, work / 'Android.bp.before')
            expected = work / 'expected' / 'Android.bp'
            expected.parent.mkdir()
            shutil.copyfile(blueprint, expected)
            bpmodify = rom / 'out/host/linux-x86/bin/bpmodify'
            run([bpmodify, '-w', '-m', interface, '-parameter', 'versions_with_info',
                 '-add-literal', '{version: "1", imports: []}', expected], 'expected-version')
            run([bpmodify, '-w', '-m', interface, '-parameter', 'frozen', '-set-bool', 'true',
                 expected], 'expected-frozen')
            assert expected.read_bytes() == frozen_blueprint.read_bytes(), 'Unexpected frozen Blueprint changes'
            frozen = mirror / relative / 'aidl_api' / interface / '1'
            target = device / relative / 'aidl_api' / interface / '1'
            assert frozen.is_dir() and not target.exists()
            dump = rom / 'out/soong/.intermediates' / 'device/xiaomi/sheng' / relative / (
                interface + '_interface') / 'dump'
            frozen_files = {path.relative_to(frozen): path for path in frozen.rglob('*') if path.is_file()}
            assert set(map(str, frozen_files)) == {'.hash', 'vendor/lineage/sheng/stylus/IPenController.aidl'}
            for name, path in frozen_files.items():
                assert not path.is_symlink() and path.read_bytes() == (dump / name).read_bytes()
            api_hash = (frozen / '.hash').read_text().strip()
            assert re.fullmatch(r'[0-9a-f]{40}', api_hash)
            generated_hash = work / 'api.hash'
            run(['bash', rom / 'system/tools/aidl/build/hash_gen.sh', frozen,
                 'latest-version', generated_hash], 'recomputed-hash')
            assert generated_hash.read_text().strip() == api_hash

            # The source directory is new; preserve the old Blueprint before replacing it.
            shutil.copytree(frozen, target)
            blueprint.write_bytes(frozen_blueprint.read_bytes())
            run(['python3', device / 'tools/verify_device_source_mirror.py',
                 '--workspace', workspace, '--rom', rom, '--path', relative,
                 '--reject-extra', '--output', work / 'source-mirror.json'], 'source-mirror')
            receipt.update(passed=True, api_frozen=True, version=1, api_hash=api_hash,
                           frozen_blueprint_sha256=sha(blueprint),
                           frozen_files_sha256={str(name): sha(path) for name, path in frozen_files.items()},
                           guard_sha256=sha(args.guard), bpmodify_sha256=sha(bpmodify),
                           hash_generator_sha256=sha(rom / 'system/tools/aidl/build/hash_gen.sh'))
    except BaseException as error:
        receipt['error'] = repr(error)
        raise
    finally:
        (work / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps(dict(work=str(work), passed=receipt['passed'], api_frozen=receipt['api_frozen'],
                             api_hash=receipt.get('api_hash'), error=receipt.get('error'))))


if __name__ == '__main__':
    main()
