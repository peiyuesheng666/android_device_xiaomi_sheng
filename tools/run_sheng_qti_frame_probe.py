#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check real AVC frame output from an isolated QTI candidate on ca10ede3 A."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess

from run_sheng_qti_load_groups_probe import STATE_COMMAND, identities, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--adb', type=Path, required=True)
    args = parser.parse_args()
    build = args.build.resolve(strict=True)
    fixture = args.fixture.resolve(strict=True)
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    tools = Path(__file__).resolve().parent
    source = tools.parent / 'interfaces/compat/codec2'
    evidence = json.loads((build / 'build.json').read_text())
    reference = json.loads((fixture / 'fixture.json').read_text())
    receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), serial='ca10ede3',
                   build=str(build), fixture=str(fixture), passed=False,
                   hal_registered=False, flashed=False, system_service_restarted=False,
                   product_integrated=False, normal_module_build_passed=False,
                   video_stream_processing_tested=False, video_boot_failure_fixed=False,
                   frame_checks=[], build_receipt_sha256=sha(build / 'build.json'),
                   fixture_receipt_sha256=sha(fixture / 'fixture.json'))
    commands = []
    original = None

    def local_path(path):
        if args.adb.suffix.lower() == '.exe':
            return subprocess.check_output(['wslpath', '-w', str(path)], text=True).strip()
        return str(path)

    def call(label, *arguments):
        command = [str(args.adb), '-s', 'ca10ede3', *arguments]
        result = subprocess.run(command, capture_output=True, timeout=55)
        (work / (label + '.txt')).write_bytes(result.stdout + result.stderr)
        commands.append(dict(command=command, exit_code=result.returncode, output=label + '.txt'))
        (work / 'runtime-commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        return result

    def device_hashes(label, paths):
        result = call(label, 'shell', 'sha256sum ' + ' '.join(paths))
        result.check_returncode()
        return {Path(name).name: digest for digest, name in
                (line.split() for line in result.stdout.decode().splitlines())}

    try:
        assert evidence['compiled'] and evidence['seccomp_enabled']
        assert evidence['frame_diagnostic'] and not evidence['product_integrated']
        assert not evidence['normal_module_build_passed']
        assert all(sha(source / name) == digest for name, digest in evidence['source_hashes'].items())
        assert all(sha(tools / name) == digest
                   for name, digest in evidence['diagnostic_source_hashes'].items())
        assert reference['passed'] and reference['width'] == reference['height'] == 128
        assert reference['frame_count'] == reference['fps'] == 8
        assert sha(tools / 'prepare_sheng_qti_frame_fixture.py') == reference['generator_sha256']
        for name, key in [('fixture.avc', 'fixture_sha256'), ('fixture.index', 'index_sha256'),
                          ('reference.yuv', 'reference_sha256'), ('source.yuv', 'source_sha256')]:
            assert sha(fixture / name) == reference[key]
            shutil.copyfile(fixture / name, work / name)
        shutil.copyfile(fixture / 'fixture.json', work / 'fixture.json')
        for name in ('build.json', 'commands.json', 'bootstrap-compile.log', 'bootstrap-link.log',
                     'payload-compile.log', 'payload-link.log'):
            shutil.copyfile(build / name, work / name)

        before = call('before-state', 'shell', STATE_COMMAND)
        before.check_returncode()
        original = identities(before.stdout)
        assert original['slot'] == '_a' and original['selinux'] == 'Enforcing'
        assert original['kernel'] == '5.15.220-gf9ca2b71f672'
        assert set(original['services']) == {
            'media.hwcodec', 'dolbycodec2', 'vendor.dolby.media.c2@1.0-service'}
        receipt['before'] = original
        libraries = re.findall(r'"(lib[^"\n]+\.so)"', (source / 'qti_load_groups.h').read_text())
        libraries += ['libqcodec2_core.so', 'libcodec2_hidl@1.0.so']
        assert len(libraries) == len(set(libraries))
        product = args.rom / 'out/target/product/sheng/vendor'
        expected = {name: sha(product / 'lib64' / name) for name in libraries}
        assert device_hashes('device-inputs', ['/vendor/lib64/' + name for name in libraries]) == expected
        receipt['input_hashes'] = expected
        policies = ['codec2.vendor.base-arm64.policy', 'codec2.vendor.ext-arm64.policy']
        expected = {name: sha(product / 'etc/seccomp_policy' / name) for name in policies}
        assert device_hashes('device-policies', ['/vendor/etc/seccomp_policy/' + name
                                                for name in policies]) == expected
        receipt['policy_hashes'] = expected

        assert re.fullmatch(r'[A-Za-z0-9_-]+', work.name)
        remote = '/data/local/tmp/' + work.name
        receipt['remote'] = remote
        call('prepare-remote', 'shell', 'mkdir ' + remote + ' && mkdir ' + remote + '/out').check_returncode()
        uploads = {}
        for kind, output in evidence['outputs'].items():
            binary = Path(output['path'])
            assert sha(binary) == output['sha256']
            local = work / binary.name
            shutil.copyfile(binary, local)
            call('push-' + kind, 'push', local_path(local), remote + '/' + binary.name).check_returncode()
            uploads[binary.name] = output['sha256']
        for name in ('fixture.avc', 'fixture.index'):
            call('push-' + name, 'push', local_path(work / name), remote + '/' + name).check_returncode()
            uploads[name] = sha(work / name)
        assert device_hashes('uploaded-inputs', [remote + '/' + name for name in uploads]) == uploads
        receipt['uploaded_hashes'] = uploads
        call('executable', 'shell', 'chmod 755 ' + remote + '/sheng-qti-codec2-bootstrap').check_returncode()
        result = call('probe', 'shell', 'env LD_LIBRARY_PATH=' + remote +
                      ':/vendor/lib64:/system/lib64 timeout -s KILL 35 ' +
                      remote + '/sheng-qti-codec2-bootstrap --frame-probe ' +
                      remote + '/fixture.avc ' + remote + '/fixture.index ' + remote + '/out')
        output = result.stdout.decode(errors='replace')
        receipt.update(exit_code=result.returncode, video_stream_processing_tested=True,
                       seccomp_confirmed='QTI_FRAMES: no_new_privs=1 seccomp=2' in output,
                       frame_processing_completed=(result.returncode == 0 and
                           'QTI_FRAMES: decoded_count=8 eos=1' in output and
                           'QTI_FRAMES: stop=0 detach=0 release=0 result=0' in output and
                           'QTI_FRAMES: natural process teardown pending' in output))
        decoded = work / 'decoded'
        decoded.mkdir()
        receipt['output_pull_exit_codes'] = {}
        for frame in reference['frames']:
            name = 'frame-' + str(frame['index']) + '.yuv'
            pulled = call('pull-' + name, 'pull', remote + '/out/' + name,
                          local_path(decoded / name))
            receipt['output_pull_exit_codes'][name] = pulled.returncode
        reference_data = (work / 'reference.yuv').read_bytes()
        frame_bytes = 128 * 128 * 3 // 2
        for frame in reference['frames']:
            index = frame['index']
            path = work / 'decoded' / ('frame-' + str(index) + '.yuv')
            check = dict(index=index, present=path.is_file(), exact=False)
            if path.is_file():
                data = path.read_bytes()
                expected_data = reference_data[index * frame_bytes:(index + 1) * frame_bytes]
                check.update(bytes=len(data), sha256=sha(path), expected_sha256=frame['yuv_sha256'])
                if len(data) == len(expected_data) == frame_bytes:
                    differences = [abs(a - b) for a, b in zip(data, expected_data)]
                    check.update(exact=data == expected_data,
                                 differing_bytes=sum(value != 0 for value in differences),
                                 max_absolute_difference=max(differences),
                                 mean_absolute_difference=sum(differences) / len(differences))
            receipt['frame_checks'].append(check)
        receipt['all_frames_exact'] = (len(receipt['frame_checks']) == 8 and
                                      all(frame['exact'] for frame in receipt['frame_checks']))
        print(output)
    except Exception as error:
        receipt['error'] = repr(error)
    finally:
        if original is not None:
            try:
                after = call('after-state', 'shell', STATE_COMMAND)
                after.check_returncode()
                receipt['after'] = identities(after.stdout)
                receipt['services_and_baseline_state_unchanged'] = receipt['after'] == original
            except Exception as error:
                receipt['after_state_error'] = repr(error)
        receipt['passed'] = all(receipt.get(key) is True for key in
            ('frame_processing_completed', 'seccomp_confirmed', 'all_frames_exact',
             'services_and_baseline_state_unchanged'))
        if receipt.get('video_stream_processing_tested') and not receipt['passed']:
            try:
                call('recent-logcat', 'shell', 'logcat -d -t 250')
            except Exception as error:
                receipt['logcat_error'] = repr(error)
        (work / 'runtime.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps(dict(work=str(work), passed=receipt['passed'], exit_code=receipt.get('exit_code'),
                             frames=receipt['frame_checks'], error=receipt.get('error')), indent=2))
    raise SystemExit(0 if receipt['passed'] else 1)


if __name__ == '__main__':
    main()
