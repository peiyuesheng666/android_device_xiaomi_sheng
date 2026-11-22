#!/usr/bin/env python3
"""Test the uninstalled QTI bootstrap and its real wrapper without HAL registration."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess

from run_sheng_qti_load_groups_probe import STATE_COMMAND, identities, sha
from build_sheng_qti_bootstrap_candidate import PROFILES, profile_libraries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--adb', type=Path, required=True)
    args = parser.parse_args()
    build = args.build.resolve(strict=True)
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parents[1] / 'interfaces/compat/codec2'
    evidence = json.loads((build / 'build.json').read_text())
    profile_name = evidence.get('profile', 'video')
    profile = PROFILES[profile_name]
    state_command = STATE_COMMAND.replace('media.hwcodec|', 'media.hwcodec|media.audio.qc.codec|mediaserver|')
    assert evidence['compiled'] and evidence['seccomp_enabled']
    assert not evidence['product_integrated']
    assert all(sha(source / name) == digest for name, digest in evidence['source_hashes'].items())
    normal_build = evidence.get('normal_module_build_passed') is True
    names = ['build.json', 'commands.json']
    if normal_build:
        from record_sheng_qti_bootstrap_build import completed_normal_build
        normal_run = Path(evidence['normal_build'])
        completed_normal_build(normal_run, profile_name)
        assert sha(normal_run / 'status.json') == evidence['normal_build_status_sha256']
        names += ['normal-status.json', 'normal-source-sync.json', 'normal-source-mirror.json',
                  'normal-prebuild-upstream-audit.json', 'normal-postbuild-upstream-audit.json',
                  'normal-prebuild-recovery-upstream-audit.json', 'bootstrap-elf.txt', 'payload-elf.txt']
    else:
        names += ['bootstrap-compile.log', 'bootstrap-link.log', 'payload-compile.log', 'payload-link.log']
    for name in names:
        shutil.copyfile(build / name, work / name)
    receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), serial='ca10ede3',
                   profile=profile_name,
                   build=str(build), hal_registered=False, flashed=False,
                   system_service_restarted=False, seccomp_enabled=True,
                   normal_module_build_passed=normal_build, product_integrated=False,
                   build_receipt_sha256=sha(build / 'build.json'),
                   output_hashes={kind: output['sha256'] for kind, output in evidence['outputs'].items()},
                   video_boot_failure_fixed=False, passed=False)

    def call(label, *arguments):
        result = subprocess.run([str(args.adb), '-s', 'ca10ede3', *arguments],
                                capture_output=True, timeout=55)
        (work / (label + '.txt')).write_bytes(result.stdout + result.stderr)
        return result

    remote = None
    try:
        before = call('before-state', 'shell', state_command)
        before.check_returncode()
        original = identities(before.stdout)
        assert original['slot'] == '_a' and original['selinux'] == 'Enforcing'
        assert original['kernel'] == '5.15.220-gf9ca2b71f672'
        assert set(original['services']) == {
            'media.hwcodec', 'media.audio.qc.codec', 'mediaserver',
            'dolbycodec2', 'vendor.dolby.media.c2@1.0-service'}
        receipt['before'] = original
        libraries = profile_libraries(source, profile_name)
        libraries += [profile['core'], 'libcodec2_hidl@1.0.so']
        if profile_name == 'audio':
            libraries += ['libqc2audio_base.so', 'libqc2audio_utils.so',
                          'libqc2audio_platform.so', 'libqc2audio_hooks.so']
        assert len(libraries) == len(set(libraries))
        expected = {name: sha(args.rom / 'out/target/product/sheng/vendor/lib64' / name)
                    for name in libraries}
        inputs = call('device-inputs', 'shell',
                      'sha256sum ' + ' '.join('/vendor/lib64/' + name for name in libraries))
        inputs.check_returncode()
        actual = {Path(name).name: digest for digest, name in
                  (line.split() for line in inputs.stdout.decode().splitlines())}
        assert actual == expected
        receipt['input_hashes'] = expected
        policies = [profile['policy_prefix'] + '.vendor.' + suffix + '-arm64.policy'
                    for suffix in ('base', 'ext')]
        policy_expected = {name: sha(args.rom / 'out/target/product/sheng/vendor/etc/seccomp_policy' / name)
                           for name in policies}
        checked = call('device-policies', 'shell', 'sha256sum ' + ' '.join(
            '/vendor/etc/seccomp_policy/' + name for name in policies))
        checked.check_returncode()
        policy_actual = {Path(name).name: digest for digest, name in
                         (line.split() for line in checked.stdout.decode().splitlines())}
        assert policy_actual == policy_expected
        receipt['policy_hashes'] = policy_expected
        baseline = call('registered-components', 'shell', 'lshal debug '
                        'android.hardware.media.c2@1.0::IComponentStore/' + profile['instance'])
        baseline.check_returncode()
        registered_names = re.findall(r'^    name: (\S+)$', baseline.stdout.decode().replace('\r', ''), re.M)
        assert len(registered_names) == profile['component_count']
        receipt['registered_component_names'] = registered_names
        assert re.fullmatch(r'[A-Za-z0-9_-]+', work.name)
        remote = '/data/local/tmp/' + work.name
        call('prepare-remote', 'shell', 'mkdir -p ' + remote).check_returncode()
        for kind, output in evidence['outputs'].items():
            binary = Path(output['path'])
            assert sha(binary) == output['sha256']
            local = work / binary.name
            shutil.copyfile(binary, local)
            path = str(local)
            if args.adb.suffix.lower() == '.exe':
                path = subprocess.check_output(['wslpath', '-w', path], text=True).strip()
            call('push-' + kind, 'push', path, remote + '/' + binary.name).check_returncode()
        uploaded = call('executable', 'shell',
            'chmod 755 ' + remote + '/' + profile['bootstrap'] + '; sha256sum ' +
            remote + '/' + profile['bootstrap'] + ' ' + remote + '/' + profile['payload'])
        uploaded.check_returncode()
        hashes = {Path(name).name: digest for digest, name in
                  (line.split() for line in uploaded.stdout.decode().splitlines())}
        assert all(hashes[Path(out['path']).name] == out['sha256']
                   for out in evidence['outputs'].values())
        result = call('probe', 'shell', 'env LD_LIBRARY_PATH=' + remote +
                      ':/vendor/lib64:/system/lib64 timeout -s KILL 35 ' +
                      remote + '/' + profile['bootstrap'] + ' --factory-probe')
        output = result.stdout.decode(errors='replace')
        receipt['exit_code'] = result.returncode
        receipt['component_enumeration_matches_registered_service'] = sorted(registered_names) == sorted(
            re.findall(r'^QTI_PAYLOAD: component=(\S+) type=', output, re.M))
        receipt['wrapper_enumeration_natural_exit_passed'] = (
            result.returncode == 0 and 'platform_wrapper_size=288 status=0' in output and
            'component_count=' + str(profile['component_count']) in output and
            'no_new_privs=1 seccomp=2' in output and
            'interface_create_release_count=' + str(profile['component_count']) in output and
            'wrapper and store released; natural process teardown pending' in output)
        receipt['actual_component_create_release_passed'] = (
            result.returncode == 0 and 'component_create_release_count=' + str(len(profile['components'])) in output and
            all('actual_component=' + name + ' status=0 available=1' in output and
                'actual_component_released=' + name in output
                for name in profile['components']))
        if profile_name == 'video':
            receipt['actual_video_component_create_release_passed'] = receipt['actual_component_create_release_passed']
        after = call('after-state', 'shell', state_command)
        after.check_returncode()
        receipt['after'] = identities(after.stdout)
        receipt['services_and_baseline_state_unchanged'] = receipt['after'] == original
        receipt['passed'] = receipt['wrapper_enumeration_natural_exit_passed'] and \
            receipt['actual_component_create_release_passed'] and \
            receipt['component_enumeration_matches_registered_service'] and \
            receipt['services_and_baseline_state_unchanged']
        print(output)
        print(result.stderr.decode(errors='replace'))
    except Exception as error:
        receipt['error'] = repr(error)
        raise
    finally:
        if remote is not None:
            cleanup = call('cleanup', 'shell', 'rm -f ' + remote + '/' + profile['bootstrap'] +
                           ' ' + remote + '/' + profile['payload'] + '; rmdir ' + remote)
            receipt['remote_files_removed'] = cleanup.returncode == 0
            receipt['passed'] = receipt['passed'] and receipt['remote_files_removed']
        (work / 'runtime.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps(receipt, indent=2))
    if not receipt['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
