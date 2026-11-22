#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Install the sealed product application layout and verify the complete installed chain."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8*1024*1024), b''): digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--flash', action='store_true')
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[4]
    device = workspace/'device/xiaomi/sheng'
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    adb = workspace/'tools/platform-tools/adb.exe'
    fastboot = workspace/'tools/platform-tools/fastboot.exe'
    package_path = args.package.resolve()
    package_hash = sha(package_path)
    package = json.loads(package_path.read_text())
    logical = {'system', 'system_ext', 'product', 'vendor', 'odm', 'system_dlkm', 'vendor_dlkm'}
    allowed = logical | {'boot', 'init_boot', 'vendor_boot', 'recovery', 'dtbo', 'vbmeta', 'vbmeta_system'}
    ui_update = package.get('kind') == 'product-pen-ui'
    changed = {'product', 'vbmeta_system'} if ui_update else {'product', 'system_ext', 'vbmeta_system'}
    receipt = dict(started_utc=datetime.now(timezone.utc).isoformat(), completed=False,
                   serial='ca10ede3', slot='a', package_sha256=package_hash, flashed_partitions=[],
                   postboot_partitions_verified=[], commands=[])

    def save(): (output/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    def call(tool, *arguments, timeout=60):
        result = subprocess.run([str(tool), '-s', 'ca10ede3', *map(str, arguments)], capture_output=True, timeout=timeout)
        text = (result.stdout+result.stderr).decode(errors='replace').strip()
        receipt['commands'].append(dict(tool=tool.name, arguments=list(map(str, arguments)),
                                       returncode=result.returncode, output=text))
        save()
        if result.returncode: raise RuntimeError(text)
        return text
    def shell(command): return call(adb, 'shell', command)
    def identity(restore=False):
        for name, value in (('ro.product.device', 'sheng'), ('ro.boot.slot_suffix', '_a'),
                            ('sys.boot_completed', '1'), ('ro.boot.flash.locked', '0')):
            assert shell('getprop '+name) == value, name
        uid = shell('id -u')
        if uid == '2000' and restore and not receipt.get('debug_root_restored'):
            call(adb, 'root')
            receipt['debug_root_restored'] = True
            raise RuntimeError('Reconnecting debug adbd')
        assert uid == '0' and shell('getenforce') == 'Enforcing'
        assert shell('uname -r') == '5.15.220-gf9ca2b71f672'
    def verify_partition(row):
        name = row['partition']
        assert name in allowed and re.fullmatch(r'[0-9a-f]{64}', row['sha256']) and row['bytes'] > 0
        command = ('sha256sum /dev/block/mapper/'+name+'_a') if name in logical else (
            'head -c '+str(row['bytes'])+' /dev/block/by-name/'+name+'_a | sha256sum')
        assert shell(command).split()[0] == row['sha256'], name
    def wait(check, seconds):
        until, last = time.monotonic()+seconds, None
        while time.monotonic() < until:
            try: check(); return
            except Exception as error: last = error
            time.sleep(2)
        raise RuntimeError('Device transition timed out: '+str(last))
    def fastboot_state(userspace):
        for name, value in (('product', 'sheng'), ('current-slot', 'a'), ('is-userspace', 'yes' if userspace else 'no')):
            assert re.search(r'(?m)^'+name+r':\s*'+value+r'\s*$', call(fastboot, 'getvar', name, timeout=10))

    try:
        assert package['kind'] in ('product-app-layout', 'product-pen-ui')
        for key in ('complete_avb_chain_verified', 'partition_sizes_unchanged', 'policy_and_vintf_inputs_unchanged',
                    'native_service_unchanged', 'systemui_unchanged', 'native_c_staging'):
            assert package[key] is True, key
        assert package['e_drive_swap_allowed'] is False and package['normal_module_build_passed'] is False
        catalog = json.loads((device/'configs/product-apps.json').read_text())
        assert package['applications'] == catalog['applications']
        if ui_update:
            assert package['targeted_ui_build_passed'] is True and not package['removals']
            build_path = workspace/package['build_receipt']
            assert sha(build_path) == package['build_receipt_sha256']
            build = json.loads(build_path.read_text())
            assert build['passed'] and build['native_service_unchanged'] and build['policy_unchanged']
            paths = {'app/ShengPenSettings/ShengPenSettings.apk', 'priv-app/ShengStylus/ShengStylus.apk'}
            if package.get('ime_updated'): paths.add('app/ShengSogouIme/ShengSogouIme.apk')
            for relative in paths:
                assert package['entries']['product'][relative]['sha256'] == build['apk_files']['product/'+relative]['sha256']
            old_paths = set()
        else:
            assert package['installed_application_bytes_preserved'] is True
            paths = {r['path'] for r in catalog['applications']+catalog['companions']}
            old_paths = paths-{r['path'] for r in catalog['applications'] if r.get('new_source')}
            assert set(package['removals']) == {'system_ext'} and set(package['removals']['system_ext']) == old_paths
        assert set(package['entries']) == {'product'} and set(package['entries']['product']) == paths
        for relative in old_paths:
            assert package['removals']['system_ext'][relative] == package['entries']['product'][relative]['sha256']
        for part in changed-{'vbmeta_system'}: assert package['partition_reports'][part]['metadata_preserved']
        baseline_relative = Path(package['baseline_manifest'])
        assert not baseline_relative.is_absolute() and '..' not in baseline_relative.parts
        baseline_path = workspace/baseline_relative
        assert sha(baseline_path) == package['baseline_manifest_sha256']
        baseline = json.loads(baseline_path.read_text())
        assert baseline['complete_avb_chain_verified']
        assert baseline.get('stylus_native_service_unchanged', baseline['native_service_unchanged'])
        old = baseline['files']+baseline['unchanged_partition_files']
        assert len(old) == 14 and {r['partition'] for r in old} == allowed and package['baseline_partitions'] == old
        assert {r['partition'] for r in package['files']} == changed
        assert package['unchanged_partition_files'] == [r for r in old if r['partition'] not in changed]
        for relative, digest in package['source_sha256'].items(): assert sha(device/relative) == digest, relative
        images = {}
        for row in package['files']:
            path = package_path.parent/row['name']
            assert path.stat().st_size == row['bytes'] and sha(path) == row['sha256']
            assert row['bytes'] == next(r['bytes'] for r in old if r['partition'] == row['partition'])
            images[row['partition']] = subprocess.check_output(['wslpath', '-w', str(path)], text=True).strip()
        identity()
        for row in old: verify_partition(row)
        receipt['live_baseline_verified'] = True
        for app in catalog['applications']:
            (output/(app['module']+'-before.txt')).write_text(shell('dumpsys package '+app['package']))
        print('Exact installed baseline, application copies and all partition sizes verified.', flush=True)
        if args.flash:
            for app in catalog['applications']:
                name = app['module']
                caches = shell('find /data/system/package_cache -mindepth 2 -maxdepth 2 -type f -name "'+name+'-*" -print')
                for remote in caches.splitlines():
                    assert re.fullmatch(r'/data/system/package_cache/[0-9a-f]{40}/'+name+r'-[0-9]+--?[0-9]+', remote)
                    blob = subprocess.check_output([str(adb), '-s', 'ca10ede3', 'exec-out', 'cat', remote])
                    (output/(name+'-'+Path(remote).parent.name+'.cache')).write_bytes(blob)
                    shell('rm -- '+remote)
            call(adb, 'reboot', 'fastboot')
            wait(lambda: fastboot_state(True), 120)
            for part in (('product',) if ui_update else ('product', 'system_ext')):
                print(call(fastboot, 'flash', part+'_a', images[part], timeout=300), flush=True)
                receipt['flashed_partitions'].append(part); save()
            call(fastboot, 'reboot', 'bootloader')
            wait(lambda: fastboot_state(False), 120)
            assert re.search(r'(?m)^unlocked:\s*yes\s*$', call(fastboot, 'getvar', 'unlocked'))
            print(call(fastboot, 'flash', 'vbmeta_system_a', images['vbmeta_system']), flush=True)
            receipt['flashed_partitions'].append('vbmeta_system'); save()
            call(fastboot, 'reboot')
            wait(lambda: identity(True), 240)
            for row in package['files']+package['unchanged_partition_files']:
                verify_partition(row)
                receipt['postboot_partitions_verified'].append(row['partition']); save()
            assert set(receipt['postboot_partitions_verified']) == allowed
            print('Booted Enforcing; all fourteen partition readbacks match.', flush=True)
        assert sha(package_path) == package_hash
        receipt['completed'] = True
    except BaseException as error:
        receipt['error'] = repr(error)
        raise
    finally:
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat(); save()
        print(output, flush=True)


if __name__ == '__main__':
    main()
