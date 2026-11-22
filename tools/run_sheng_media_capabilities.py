#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Inspect declared media capabilities without playback or a license request."""
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
    args = parser.parse_args()
    tools = Path(__file__).resolve().parent
    workspace = tools.parents[3]
    build = json.loads((args.build / 'build.json').read_text())
    jar = args.build / 'sheng-media-capabilities.jar'
    assert build['passed'] and not build['ninja_graph_loaded']
    assert build['source_sha256'] == sha(tools / 'ShengMediaCapabilitiesProbe.java')
    assert build['jar_sha256'] == sha(jar)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(jar, output / 'probe.jar')
    adb = workspace / 'tools/platform-tools/adb.exe'
    remote = '/data/local/tmp/sheng-media-capabilities-' + uuid.uuid4().hex[:12]
    receipt = dict(inspection_completed=False, started_utc=datetime.now(timezone.utc).isoformat(),
                   jar_sha256=sha(jar), source_sha256=build['source_sha256'], commands=[],
                   camera_used=False, screenshot_taken=False, network_used=False, playback_used=False)

    def call(label, *arguments):
        result = subprocess.run([str(adb), '-s', 'ca10ede3', *arguments], capture_output=True, timeout=40)
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
        text = call('probe', 'shell', 'CLASSPATH=' + remote + '/probe.jar timeout 30 app_process / '
                    'ShengMediaCapabilitiesProbe')
        rows = [line[len('MEDIA_CAPABILITIES '):] for line in text.splitlines()
                if line.startswith('MEDIA_CAPABILITIES ')]
        assert len(rows) == 1
        capabilities = json.loads(rows[0])
        (output / 'capabilities.json').write_text(json.dumps(capabilities, indent=2) + '\n')
        ape = [c for c in capabilities['codecs'] if c['mime'] == 'audio/x-ape']
        assert [c['name'] for c in ape] == ['c2.qti.ape.hw.decoder']
        receipt.update(inspection_completed=True, ape_hardware_only_advertised=True,
                       capabilities_sha256=sha(output / 'capabilities.json'))
        print(json.dumps(dict(ape=ape, drm=capabilities['drm'], display=capabilities['display']), indent=2))
    except BaseException as error:
        receipt.update(inspection_completed=False, error=repr(error))
    finally:
        try:
            receipt['after'] = state('after')
            assert receipt['after']['boot_id'] == receipt['before']['boot_id']
            assert all(receipt['after']['services'].get(k) == v for k, v in receipt['before']['services'].items())
            receipt['existing_media_services_unchanged'] = True
            call('crashes', 'logcat', '-b', 'crash', '-d', '-v', 'threadtime')
        except BaseException as error:
            receipt.update(inspection_completed=False, state_error=repr(error))
        if created:
            try:
                call('cleanup', 'shell', 'rm -f ' + remote + '/probe.jar && rmdir ' + remote)
                receipt['temporary_files_removed'] = True
            except BaseException as error:
                receipt.update(inspection_completed=False, cleanup_error=repr(error))
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    if not receipt['inspection_completed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
