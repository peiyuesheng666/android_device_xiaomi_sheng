#!/usr/bin/env python3
"""Run the temporary factory experiment on ca10ede3 A, preserving service state."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

STATE_COMMAND = ('getprop ro.boot.slot_suffix; uname -r; getenforce; '
                 'ps -A | grep -E "media.hwcodec|dolbycodec2|vendor.dolby.media"')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identities(output):
    lines = output.decode().replace('\r', '').splitlines()
    return dict(slot=lines[0], kernel=lines[1], selinux=lines[2],
                services={line.split()[-1]: int(line.split()[1]) for line in lines[3:]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True,
                        help='New receipt directory on C for Windows adb.exe')
    parser.add_argument('--adb', type=Path, required=True)
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    build = args.build.resolve(strict=True)
    evidence = json.loads((build / 'build.json').read_text())
    assert evidence['seccomp_enabled'] and not evidence['hal_registration']
    assert not evidence['product_integrated'] and evidence['compiled']
    binary = Path(evidence['output'])
    assert sha(binary) == evidence['output_sha256']
    for name in ('build.json', 'commands.json', 'qti-field-bindings.h', 'compile.log', 'link.log'):
        shutil.copyfile(build / name, work / name)
    local_binary = work / binary.name
    shutil.copyfile(binary, local_binary)
    receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), serial='ca10ede3',
                   build=str(build), output_sha256=evidence['output_sha256'],
                   seccomp_enabled=True, hal_registered=False, flashed=False,
                   system_service_restarted=False, product_integrated=False,
                   video_boot_failure_fixed=False, passed=False)

    def call(label, *arguments, timeout=55):
        result = subprocess.run([str(args.adb), '-s', 'ca10ede3', *arguments],
                                capture_output=True, timeout=timeout)
        (work / (label + '.txt')).write_bytes(result.stdout + result.stderr)
        return result

    try:
        before = call('before-state', 'shell', STATE_COMMAND)
        before.check_returncode()
        original = identities(before.stdout)
        assert original['slot'] == '_a' and original['selinux'] == 'Enforcing'
        assert original['kernel'] == '5.15.220-gf9ca2b71f672'
        assert set(original['services']) == {
            'media.hwcodec', 'dolbycodec2', 'vendor.dolby.media.c2@1.0-service'}
        receipt['before'] = original
        paths = ' '.join('/vendor/lib64/' + entry['library'] for entry in evidence['inputs'])
        inputs = call('device-inputs', 'shell', 'sha256sum ' + paths)
        inputs.check_returncode()
        hashes = {Path(path).name: digest for digest, path in
                  (line.split() for line in inputs.stdout.decode().splitlines())}
        assert all(hashes[entry['library']] == entry['sha256'] for entry in evidence['inputs'])
        receipt['all_seven_input_hashes_matched'] = True
        remote = '/data/local/tmp/' + work.name
        assert re.fullmatch(r'[A-Za-z0-9_-]+', work.name)
        call('prepare-remote', 'shell', 'mkdir -p ' + remote).check_returncode()
        local_path = str(local_binary)
        if args.adb.suffix.lower() == '.exe':
            local_path = subprocess.check_output(['wslpath', '-w', local_path], text=True).strip()
        call('push', 'push', local_path, remote + '/probe').check_returncode()
        checked = call('executable', 'shell',
                       'chmod 755 ' + remote + '/probe; sha256sum ' + remote + '/probe')
        checked.check_returncode()
        assert checked.stdout.decode().split()[0] == evidence['output_sha256']
        result = call('probe', 'shell', 'env LD_LIBRARY_PATH=/vendor/lib64:/system/lib64 '
                      'timeout -s KILL 35 ' + remote + '/probe')
        output = result.stdout.decode(errors='replace')
        receipt.update(exit_code=result.returncode,
                       binding_checks=re.findall(r'stage=(\S+) own_object_bindings=(\d+)', output))
        receipt['enumeration_and_natural_exit_passed'] = (
            result.returncode == 0 and 'component_count=19' in output and
            'stage=store-released own_object_bindings=318' in output and
            'natural process teardown pending' in output)
        after = call('after-state', 'shell', STATE_COMMAND)
        after.check_returncode()
        receipt['after'] = identities(after.stdout)
        receipt['services_and_baseline_state_unchanged'] = receipt['after'] == original
        receipt['passed'] = (receipt['enumeration_and_natural_exit_passed'] and
                             receipt['services_and_baseline_state_unchanged'])
        print(output)
        print(result.stderr.decode(errors='replace'))
    except Exception as error:
        receipt['error'] = repr(error)
        raise
    finally:
        (work / 'runtime.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
