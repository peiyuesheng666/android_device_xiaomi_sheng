#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Qualify an isolated APE extractor and DSP decoder against independent PCM."""
import argparse
import bisect
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import uuid


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    device = Path(__file__).resolve().parents[1]
    workspace = device.parents[2]
    adb = workspace / 'tools/platform-tools/adb.exe'
    build_file = args.build / 'build.json'
    build = json.loads(build_file.read_text())
    assert build['passed'] and build['targeted_module_build_passed'] and not build['ninja_graph_loaded']
    assert all(sha(device / path) == digest for path, digest in build['source_sha256'].items())
    reference = json.loads((args.reference / 'receipt.json').read_text())
    fixture = args.reference / 'reference.ape'
    pcm = (args.reference / 'reference.pcm').read_bytes()
    assert sha(fixture) == reference['fixture_sha256']
    assert len(pcm) == reference['reference_pcm_bytes'] == 10668672
    assert hashlib.sha256(pcm).hexdigest() == reference['reference_pcm_sha256']
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    files = {name: Path(row['path']) for name, row in build['outputs'].items()}
    for name, path in files.items():
        assert sha(path) == build['outputs'][name]['sha256']
    files['reference.ape'] = fixture
    for name, path in files.items():
        shutil.copyfile(path, output / name)
    remote = '/data/local/tmp/sheng-ape-plugin-' + uuid.uuid4().hex[:12]
    receipt = dict(passed=False, started_utc=datetime.now(timezone.utc).isoformat(),
                   build_receipt=str(build_file), build_receipt_sha256=sha(build_file),
                   source_sha256=build['source_sha256'], fixture_sha256=sha(fixture),
                   plugin_registered=False, flashed=False, playback_used=False,
                   microphone_used=False, camera_used=False, runs=[], commands=[])

    def call(label, *arguments, check=True):
        result = subprocess.run([str(adb), '-s', 'ca10ede3', *arguments], capture_output=True, timeout=40)
        (output / (label + '.stdout')).write_bytes(result.stdout)
        (output / (label + '.stderr')).write_bytes(result.stderr)
        receipt['commands'].append(dict(label=label, arguments=arguments, returncode=result.returncode))
        if check:
            result.check_returncode()
        return result

    def shell(label, command):
        return call(label, 'shell', command).stdout.decode(errors='replace').strip()

    def state(label):
        lines = shell(label, 'getprop sys.boot_completed; getenforce; '
                      'cat /proc/sys/kernel/random/boot_id; ps -A').splitlines()
        names = {'media.audio.qc.codec', 'media.hwcodec', 'mediaserver',
                 'dolbycodec2', 'vendor.dolby.media.c2@1.0-service'}
        services = {row[-1]: int(row[1]) for row in (line.split() for line in lines[3:])
                    if row and row[-1] in names}
        assert lines[:2] == ['1', 'Enforcing'] and set(services) == names
        assert re.fullmatch(r'[0-9a-f-]{36}', lines[2])
        return dict(boot_id=lines[2], selinux=lines[1], services=services)

    created = False
    try:
        receipt['before'] = state('before')
        shell('prepare', 'test ! -e ' + remote + ' && mkdir -m 0700 ' + remote)
        created = True
        for name, path in files.items():
            local = subprocess.check_output(['wslpath', '-w', str(output / name)], text=True).strip()
            call('push-' + name, 'push', local, remote + '/' + name)
            assert shell('hash-' + name, 'sha256sum ' + remote + '/' + name).split()[0] == sha(path)
        shell('permissions', 'chmod 0500 ' + remote + '/sheng-ape-extractor-probe && chmod 0400 '
              + remote + '/libshengapeextractor.so ' + remote + '/reference.ape')
        timestamps = [i * 73728 * 1000000 // 44100 for i in range(37)]
        for seek in (0, 30000000, timestamps[-1]):
            label = 'decode-' + str(seek)
            result = call(label, 'shell', 'timeout 30 ' + remote + '/sheng-ape-extractor-probe '
                          + remote + '/libshengapeextractor.so ' + remote + '/reference.ape '
                          + remote + '/decoded.pcm ' + str(seek), check=False)
            decoded = (result.stdout + result.stderr).decode(errors='replace')
            print('\n'.join(line for line in decoded.splitlines() if 'APE_PLUGIN' in line), flush=True)
            result.check_returncode()
            assert 'APE_PLUGIN passed=true' in decoded
            frame = bisect.bisect_right(timestamps, seek) - 1
            expected = pcm[frame * 73728 * 4:]
            expected_sha = hashlib.sha256(expected).hexdigest()
            actual = shell(label + '-pcm', 'sha256sum ' + remote + '/decoded.pcm; '
                           'stat -c %s ' + remote + '/decoded.pcm').splitlines()
            row = dict(seek_us=seek, first_frame=frame, pcm_sha256=actual[0].split()[0],
                       expected_pcm_sha256=expected_sha, bytes=int(actual[1]),
                       expected_bytes=len(expected), passed=False)
            receipt['runs'].append(row)
            row['passed'] = row['pcm_sha256'] == expected_sha and row['bytes'] == len(expected)
            assert row['passed'], row
            print(json.dumps(row), flush=True)
        receipt['passed'] = True
    except BaseException as error:
        receipt.update(passed=False, error=repr(error))
    finally:
        try:
            receipt['after'] = state('after')
            receipt['services_and_boot_unchanged'] = receipt['after'] == receipt.get('before')
            assert receipt['services_and_boot_unchanged']
            call('logcat', 'logcat', '-b', 'all', '-d', '-v', 'threadtime')
        except BaseException as error:
            receipt.update(passed=False, state_error=repr(error))
        if created:
            try:
                cleanup = call('cleanup', 'shell', 'rm -f ' + ' '.join(remote + '/' + name
                               for name in [*files, 'decoded.pcm']) + ' && rmdir ' + remote, check=False)
                receipt['temporary_files_removed'] = cleanup.returncode == 0
                assert receipt['temporary_files_removed']
            except BaseException as error:
                receipt.update(passed=False, cleanup_error=repr(error))
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    if not receipt['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
