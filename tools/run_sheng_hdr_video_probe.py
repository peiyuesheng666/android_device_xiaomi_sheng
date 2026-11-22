#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare Main10 decoder output and HDR metadata without rendering frames."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import uuid


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    tools = Path(__file__).resolve().parent
    workspace = tools.parents[3]
    build = json.loads((args.build / 'build.json').read_text())
    prepared = json.loads((args.fixtures / 'receipt.json').read_text())
    jar = args.build / 'sheng-hdr-video.jar'
    assert build['passed'] and not build['ninja_graph_loaded'] and prepared['passed']
    assert build['source_sha256'] == sha(tools / 'ShengHdrVideoProbe.java')
    assert build['jar_sha256'] == sha(jar)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    files = {'probe.jar': jar}
    for name in ('pq', 'hlg'):
        clip = args.fixtures / (name + '.mp4')
        reference = args.fixtures / (name + '-reference.json')
        assert sha(reference) == prepared['fixtures'][name]['reference_sha256']
        assert sha(clip) == prepared['fixtures'][name]['clip_sha256']
        assert json.loads(reference.read_text())['fixture_sha256'] == sha(clip)
        files[clip.name], files[reference.name] = clip, reference
    for name, source in files.items():
        shutil.copyfile(source, output / name)
    adb = workspace / 'tools/platform-tools/adb.exe'
    remote = '/data/local/tmp/sheng-hdr-video-' + uuid.uuid4().hex[:12]
    receipt = dict(passed=False, started_utc=datetime.now(timezone.utc).isoformat(), commands=[],
                   jar_sha256=sha(jar), source_sha256=build['source_sha256'],
                   fixture_receipt_sha256=sha(args.fixtures / 'receipt.json'),
                   camera_used=False, network_used=False, display_surface_used=False, screenshot_taken=False)

    def call(label, *arguments):
        result = subprocess.run([str(adb), '-s', 'ca10ede3', *arguments], capture_output=True, timeout=45)
        (output / (label + '.stdout')).write_bytes(result.stdout)
        (output / (label + '.stderr')).write_bytes(result.stderr)
        receipt['commands'].append(dict(label=label, arguments=arguments, returncode=result.returncode))
        result.check_returncode()
        return result.stdout.decode(errors='replace').strip()

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
        for name, source in files.items():
            local = subprocess.check_output(['wslpath', '-w', str(output / name)], text=True).strip()
            call('push-' + name, 'push', local, remote + '/' + name)
            assert call('hash-' + name, 'shell', 'sha256sum ' + remote + '/' + name).split()[0] == sha(source)
        call('permissions', 'shell', 'chmod 0444 ' + ' '.join(remote + '/' + name for name in files))
        results = {}
        receipt['results'] = results
        for name in ('pq', 'hlg'):
            command = ('CLASSPATH=' + remote + '/probe.jar timeout 30 app_process / ShengHdrVideoProbe '
                       + shlex.quote(remote + '/' + name + '.mp4') + ' '
                       + shlex.quote(remote + '/' + name + '-reference.json'))
            text = call('decode-' + name, 'shell', command)
            rows = [line[len('HDR_VIDEO '):] for line in text.splitlines() if line.startswith('HDR_VIDEO ')]
            assert len(rows) == 1
            decoded = json.loads(rows[0])
            assert decoded['passed'] and decoded['content_exact'] and decoded['metadata_checked']
            assert decoded['eos'] and len(decoded['frames']) == prepared['fixtures'][name]['frames']
            (output / (name + '-decoded.json')).write_text(json.dumps(decoded, indent=2) + '\n')
            results[name] = dict(frames=len(decoded['frames']), content_exact=True,
                                 output_colors=decoded['output_colors'])
            print(json.dumps(dict(fixture=name, **results[name])), flush=True)
        receipt.update(passed=True, results=results)
    except BaseException as error:
        receipt.update(passed=False, error=repr(error))
    finally:
        try:
            receipt['after'] = state('after')
            assert receipt['after'] == receipt['before']
            receipt['services_and_boot_unchanged'] = True
            call('crashes', 'logcat', '-b', 'crash', '-d', '-v', 'threadtime')
        except BaseException as error:
            receipt.update(passed=False, state_error=repr(error))
        if created:
            try:
                call('cleanup', 'shell', 'rm -f ' + ' '.join(remote + '/' + name for name in files)
                     + ' && rmdir ' + remote)
                receipt['temporary_files_removed'] = True
            except BaseException as error:
                receipt.update(passed=False, cleanup_error=repr(error))
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    if not receipt['passed']:
        print(json.dumps(dict(passed=False, error=receipt.get('error'), report=str(output / 'receipt.json'))), flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
