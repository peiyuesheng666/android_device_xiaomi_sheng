#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Install qualified native service repairs on the exact current A-slot baseline."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time

from flash_sheng_product_apps import sha
from build_sheng_qti_bootstrap_candidate import PROFILES
from prepare_sheng_dolby_policy_update import validate as validate_policy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--flash', action='store_true')
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[4]
    device = workspace / 'device/xiaomi/sheng'
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    package_path = args.package.resolve(strict=True)
    package_hash = sha(package_path)
    package = json.loads(package_path.read_text())
    logical = {'system', 'system_ext', 'product', 'vendor', 'odm', 'system_dlkm', 'vendor_dlkm'}
    allowed = logical | {'boot', 'init_boot', 'vendor_boot', 'recovery', 'dtbo', 'vbmeta', 'vbmeta_system'}
    ape_update = package.get('kind') == 'ape-extractor-update'
    changed = {'vendor', 'system_ext', 'vbmeta', 'vbmeta_system'} if ape_update else {'vendor', 'vbmeta'}
    adb = workspace / 'tools/platform-tools/adb.exe'
    fastboot = workspace / 'tools/platform-tools/fastboot.exe'
    receipt = dict(started_utc=datetime.now(timezone.utc).isoformat(), completed=False,
                   serial='ca10ede3', slot='a', package_sha256=package_hash, flashed_partitions=[],
                   postboot_partitions_verified=[], commands=[])

    def save():
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')

    def call(tool, *arguments, timeout=55):
        result = subprocess.run([str(tool), '-s', 'ca10ede3', *map(str, arguments)],
                                capture_output=True, timeout=timeout)
        text = (result.stdout + result.stderr).decode(errors='replace').strip()
        receipt['commands'].append(dict(tool=tool.name, arguments=list(map(str, arguments)),
                                       returncode=result.returncode, output=text))
        save()
        if result.returncode:
            raise RuntimeError(text)
        return text

    def shell(command):
        return call(adb, 'shell', command)

    def identity(restore=False):
        for key, wanted in (('ro.product.device', 'sheng'), ('ro.boot.slot_suffix', '_a'),
                            ('sys.boot_completed', '1'), ('ro.boot.flash.locked', '0')):
            assert shell('getprop ' + key) == wanted, key
        uid = shell('id -u')
        if uid == '2000' and restore and not receipt.get('debug_root_restored'):
            call(adb, 'root')
            receipt['debug_root_restored'] = True
            raise RuntimeError('Reconnecting debug adbd')
        assert uid == '0' and shell('getenforce') == 'Enforcing'
        assert shell('uname -r') == '5.15.220-gf9ca2b71f672'

    def verify_partition(row):
        name = row['partition']
        assert name in allowed and re.fullmatch(r'[0-9a-f]{64}', row['sha256'])
        assert isinstance(row['bytes'], int) and row['bytes'] > 0
        command = ('sha256sum /dev/block/mapper/' + name + '_a') if name in logical else (
            'head -c ' + str(row['bytes']) + ' /dev/block/by-name/' + name + '_a | sha256sum')
        assert shell(command).split()[0] == row['sha256'], name

    def wait(check, seconds):
        until, last = time.monotonic() + seconds, None
        while time.monotonic() < until:
            try:
                check()
                return
            except Exception as error:
                last = error
            time.sleep(2)
        raise RuntimeError('Device transition timed out: ' + str(last))

    def fastboot_state(userspace):
        for key, wanted in (('product', 'sheng'), ('current-slot', 'a'),
                            ('is-userspace', 'yes' if userspace else 'no')):
            assert re.search(r'(?m)^' + key + r':\s*' + wanted + r'\s*$',
                             call(fastboot, 'getvar', key, timeout=10))

    try:
        assert package['kind'] in ('codec2-service-update', 'vendor-runtime-update', 'ape-extractor-update')
        for key in ('complete_avb_chain_verified', 'partition_sizes_unchanged',
                    'stylus_native_service_unchanged',
                    'product_apps_unchanged', 'native_c_staging'):
            assert package[key] is True, key
        assert package['e_drive_swap_allowed'] is False
        assert package['normal_module_build_passed'] is False and not package['removals']
        assert package['partition_reports']['vendor']['metadata_preserved']
        services = {} if ape_update else package.get('qualified_services', {'video': package})
        backends = package.get('audio_backends', {})
        startup = package.get('startup_libraries', {})
        policy = None
        if package.get('qualified_policy'):
            policy_path = Path(package['qualified_policy'])
            assert sha(policy_path) == package['qualified_policy_sha256']
            policy = validate_policy(device, policy_path)
            assert package['policy_and_vintf_inputs_unchanged'] is False
            assert all(package[key] is True for key in ('boot_policy_neverallows_verified',
                'vintf_inputs_unchanged', 'precompiled_cache_ineligible_on_unchanged_partitions'))
            assert shell('sha256sum /sys/fs/selinux/policy').split()[0] == policy['active_policy_sha256']
            for part, row in policy['cache_hashes'].items():
                assert part in ('system_ext', 'product')
                assert shell('cat /' + part + '/etc/selinux/' + part + '_sepolicy_and_mapping.sha256') == row['current']
                assert shell('cat /odm/etc/selinux/precompiled_sepolicy.' + part + '_sepolicy_and_mapping.sha256') == row['cached']
        else:
            assert package['policy_and_vintf_inputs_unchanged'] is True
        assert (services or backends or startup or policy or ape_update) and set(services) <= set(PROFILES)
        assert (package['kind'] == 'vendor-runtime-update') == bool(startup or policy)
        if services:
            assert package['targeted_module_build_passed']
        else:
            assert package['targeted_native_validation_passed']
        expected_files = {path for profile in services for path in (
            'bin/hw/' + PROFILES[profile]['service'], 'lib64/' + PROFILES[profile]['payload'])}
        if policy:
            expected_files.update(policy['entries'])
            assert policy['baseline_sha256'] == package['baseline_manifest_sha256']
            for relative, entry in policy['entries'].items():
                assert package['entries']['vendor'][relative]['sha256'] == entry['sha256']
        if backends:
            catalog = json.loads((device / 'configs/audio-codec-backends.json').read_text())
            assert backends == {row['path']: row['sha256'] for row in catalog['libraries']}
            expected_files.update(backends)
            assert sha(Path(package['audio_backends_receipt'])) == package['audio_backends_receipt_sha256']
            assert json.loads(Path(package['audio_backends_receipt']).read_text())['passed']
            assert shell('getconf PAGE_SIZE') == '4096'
            for relative, digest in backends.items():
                assert package['entries']['vendor'][relative]['sha256'] == digest
        if startup:
            catalog = json.loads((device / 'configs/cacert-runtime.json').read_text())
            assert startup == {row['path']: row['sha256'] for row in catalog['libraries']}
            expected_files.update(startup)
            expected_files.add('build.prop')
            startup_receipt = Path(package['startup_receipt'])
            assert sha(startup_receipt) == package['startup_receipt_sha256']
            prepared = json.loads(startup_receipt.read_text())
            assert prepared['passed'] and prepared['kind'] == 'vendor-startup'
            properties = package['startup_property_update']
            assert properties == prepared['property_update']
            assert properties['removed'] == json.loads(
                (device / 'configs/vendor-property-cleanup.json').read_text())
            assert sha(Path(properties['source'])) == properties['sha256']
            assert package['entries']['vendor']['build.prop']['sha256'] == properties['sha256']
            assert package['partition_reports']['vendor']['baseline_entries']['build.prop'] == [
                'file', properties['baseline_sha256']]
            assert shell('getconf PAGE_SIZE') == '4096'
            for relative, digest in startup.items():
                assert package['entries']['vendor'][relative]['sha256'] == digest
        if ape_update:
            from package_sheng_ape_extractor import BASE_XML, LIBRARY, WRAPPER, qualify
            assert package['native_service_unchanged'] and package['targeted_module_build_passed']
            assert package['partition_reports']['system_ext']['metadata_preserved']
            qualifications = package['qualified_ape']
            assert set(qualifications) == {'build', 'runtime', 'host'}
            for value in qualifications.values():
                assert sha(Path(value['path'])) == value['sha256']
            build, _, _ = qualify(device, *[Path(qualifications[k]['path'])
                                           for k in ('build', 'runtime', 'host')])
            assert set(package['entries']) == {'vendor', 'system_ext'}
            assert set(package['entries']['system_ext']) == {LIBRARY}
            assert package['entries']['system_ext'][LIBRARY]['sha256'] == (
                build['outputs']['libshengapeextractor.so']['sha256'])
            assert package['entries']['vendor'][WRAPPER]['sha256'] == sha(
                device / 'configs/audio/media_codecs_c2_audio.xml')
            upstream = package['upstream_xml']
            assert sha(Path(upstream['path'])) == upstream['sha256']
            assert package['entries']['vendor'][BASE_XML]['sha256'] == upstream['sha256']
            assert package['partition_reports']['vendor']['baseline_entries'][WRAPPER] == [
                'file', upstream['sha256']]
            assert sha(Path(package['scoped_file_contexts'])) == package['scoped_file_contexts_sha256']
            expected_files = {WRAPPER, BASE_XML}
        else:
            assert set(package['entries']) == {'vendor'}
        assert set(package['entries']['vendor']) == expected_files
        baseline_relative = Path(package['baseline_manifest'])
        assert not baseline_relative.is_absolute() and '..' not in baseline_relative.parts
        baseline_path = workspace / baseline_relative
        assert sha(baseline_path) == package['baseline_manifest_sha256']
        baseline = json.loads(baseline_path.read_text())
        if ape_update:
            assert package['applications'] == baseline['applications']
            assert package['scoped_file_contexts_sha256'] == baseline['scoped_file_contexts_sha256']
        old = baseline['files'] + baseline['unchanged_partition_files']
        assert baseline['complete_avb_chain_verified'] and package['baseline_partitions'] == old
        assert len(old) == 14 and {row['partition'] for row in old} == allowed
        assert {row['partition'] for row in package['files']} == changed
        assert package['unchanged_partition_files'] == [row for row in old if row['partition'] not in changed]
        for relative, digest in package['source_sha256'].items():
            assert sha(device / relative) == digest, relative
        for service in services.values():
            assert sha(workspace / service['isolated_runtime']) == service['isolated_runtime_sha256']
            assert sha(Path(service['build_receipt'])) == service['build_receipt_sha256']
        if 'qualified_services' in package:
            elf_checks = Path(package['elf_checks'])
            assert sha(elf_checks) == package['elf_checks_sha256']
            assert json.loads(elf_checks.read_text())['passed']
        images = {}
        for row in package['files']:
            path = package_path.parent / row['name']
            assert path.stat().st_size == row['bytes'] and sha(path) == row['sha256']
            assert row['bytes'] == next(item['bytes'] for item in old if item['partition'] == row['partition'])
            images[row['partition']] = subprocess.check_output(['wslpath', '-w', str(path)], text=True).strip()
        identity()
        for row in old:
            verify_partition(row)
        receipt['live_baseline_verified'] = True
        receipt['preflight_completed'] = True
        print('Installed baseline and the signed update images verified.', flush=True)
        if args.flash:
            call(adb, 'reboot', 'fastboot')
            wait(lambda: fastboot_state(True), 120)
            for part in (('vendor', 'system_ext') if ape_update else ('vendor',)):
                print(call(fastboot, 'flash', part + '_a', images[part], timeout=180), flush=True)
                receipt['flashed_partitions'].append(part)
                save()
            call(fastboot, 'reboot', 'bootloader')
            wait(lambda: fastboot_state(False), 120)
            assert re.search(r'(?m)^unlocked:\s*yes\s*$', call(fastboot, 'getvar', 'unlocked'))
            for part in (('vbmeta_system', 'vbmeta') if ape_update else ('vbmeta',)):
                print(call(fastboot, 'flash', part + '_a', images[part]), flush=True)
                receipt['flashed_partitions'].append(part)
                save()
            call(fastboot, 'reboot')
            wait(lambda: identity(True), 240)
            for row in package['files'] + package['unchanged_partition_files']:
                verify_partition(row)
                receipt['postboot_partitions_verified'].append(row['partition'])
                save()
            assert set(receipt['postboot_partitions_verified']) == allowed
            receipt['completed'] = True
            print('Booted Enforcing; all fourteen partition readbacks match.', flush=True)
        assert sha(package_path) == package_hash
    except BaseException as error:
        receipt['error'] = repr(error)
        raise
    finally:
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        save()


if __name__ == '__main__':
    main()
