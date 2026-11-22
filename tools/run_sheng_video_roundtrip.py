#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check generated AVC/HEVC frames, optionally through ClearKey decryption."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import uuid


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--clearkey', action='store_true')
    args = parser.parse_args()
    tools = Path(__file__).resolve().parent
    workspace = tools.parents[3]
    jar = args.build / 'sheng-codec2-roundtrip.jar'
    build = json.loads((args.build / 'build.json').read_text())
    assert build['passed'] and not build['ninja_graph_loaded']
    assert build['source_sha256'] == sha(tools / 'ShengCodec2RoundTrip.java')
    assert build['jar_sha256'] == sha(jar)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(jar, output / 'probe.jar')
    remote = '/data/local/tmp/sheng-video-roundtrip-' + uuid.uuid4().hex[:12]
    adb = workspace / 'tools/platform-tools/adb.exe'
    receipt = dict(passed=False, started_utc=datetime.now(timezone.utc).isoformat(),
                   source_sha256=build['source_sha256'], jar_sha256=sha(jar), clearkey=args.clearkey,
                   camera_used=False, display_used=False, network_used=False, commands=[])

    def call(label, *arguments):
        result = subprocess.run([str(adb), '-s', 'ca10ede3', *arguments], capture_output=True, timeout=45)
        (output / (label + '.stdout')).write_bytes(result.stdout)
        (output / (label + '.stderr')).write_bytes(result.stderr)
        receipt['commands'].append(dict(label=label, arguments=arguments, returncode=result.returncode))
        result.check_returncode()
        return (result.stdout + result.stderr).decode(errors='replace').strip()

    def state(label):
        lines = call(label, 'shell', 'getprop sys.boot_completed; getenforce; '
                     'cat /proc/sys/kernel/random/boot_id; ps -A').splitlines()
        assert lines[:2] == ['1', 'Enforcing']
        names = {'media.audio.qc.codec', 'media.hwcodec', 'mediaserver', 'media.extractor',
                 'dolbycodec2', 'vendor.dolby.media.c2@1.0-service'}
        services = {row[-1]: int(row[1]) for row in map(str.split, lines[3:])
                    if row and (row[-1] in names or 'drm' in row[-1])}
        assert names <= services.keys()
        return dict(boot_id=lines[2], services=services)

    created = False
    try:
        receipt['before'] = state('before')
        call('prepare', 'shell', 'test ! -e ' + remote + ' && mkdir -m 0700 ' + remote)
        created = True
        local = subprocess.check_output(['wslpath', '-w', str(output / 'probe.jar')], text=True).strip()
        call('push', 'push', local, remote + '/probe.jar')
        assert call('hash', 'shell', 'sha256sum ' + remote + '/probe.jar').split()[0] == sha(jar)
        call('permissions', 'shell', 'chmod 0444 ' + remote + '/probe.jar')
        text = call('roundtrip', 'shell', 'CLASSPATH=' + remote + '/probe.jar timeout 40 app_process / '
                    'ShengCodec2RoundTrip' + (' --clearkey' if args.clearkey else ''))
        print('\n'.join(line for line in text.splitlines() if line.startswith('CODEC_ROUNDTRIP:')), flush=True)
        assert 'CODEC_ROUNDTRIP: passed=true codecs=4' in text
        for mime in ('video/avc', 'video/hevc'):
            rows = [line for line in text.splitlines() if line.startswith('CODEC_ROUNDTRIP: mime=' + mime)]
            assert len(rows) == 1 and 'frames=8 ' in rows[0] and 'eos=true content_checked=true' in rows[0]
            assert 'encrypted_packets=' + ('8' if args.clearkey else '0') in rows[0]
        receipt.update(passed=True, avc_frames=8, hevc_frames=8, content_checked=True)
    except BaseException as error:
        receipt.update(passed=False, error=repr(error))
    finally:
        try:
            receipt['after'] = state('after')
            assert receipt['after']['boot_id'] == receipt['before']['boot_id']
            assert all(receipt['after']['services'].get(k) == v for k, v in receipt['before']['services'].items())
            receipt['services_and_boot_unchanged'] = True
            call('logcat', 'logcat', '-b', 'all', '-d', '-v', 'threadtime')
            call('crashes', 'logcat', '-b', 'crash', '-d', '-v', 'threadtime')
        except BaseException as error:
            receipt.update(passed=False, state_error=repr(error))
        if created:
            try:
                call('cleanup', 'shell', 'rm -f ' + remote + '/probe.jar && rmdir ' + remote)
                receipt['temporary_files_removed'] = True
            except BaseException as error:
                receipt.update(passed=False, cleanup_error=repr(error))
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    if not receipt['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
