#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check ALAC HIDL pool ownership in an unregistered, temporary test service."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess

from build_sheng_qti_bootstrap_candidate import PROFILES, sha
from run_sheng_qti_load_groups_probe import STATE_COMMAND, identities


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--production-build', type=Path, required=True)
    parser.add_argument('--adb', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build = json.loads((args.build / 'build.json').read_text())
    production = json.loads((args.production_build / 'build.json').read_text())
    assert build['pool_diagnostic'] and build['profile'] == 'audio' and build['compiled']
    assert production['targeted_module_build_passed'] and not production['pool_diagnostic']
    assert build['source_hashes'] == production['source_hashes']
    source = Path(__file__).resolve().parents[1] / 'interfaces/compat/codec2'
    assert all(sha(source / name) == digest for name, digest in build['source_hashes'].items())
    assert all(sha(Path(__file__).parent / name) == digest
               for name, digest in build['diagnostic_source_hashes'].items())
    work = args.output.resolve()
    assert re.fullmatch(r'[A-Za-z0-9_-]+', work.name)
    work.mkdir(parents=True, exist_ok=False)
    remote = '/data/local/tmp/' + work.name
    profile = PROFILES['audio']
    receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), passed=False,
                   build=str(args.build), build_sha256=sha(args.build / 'build.json'),
                   production_build=str(args.production_build),
                   production_build_sha256=sha(args.production_build / 'build.json'),
                   source_hashes=build['source_hashes'], hal_registered=False,
                   flashed=False, system_service_restarted=False, seccomp_enabled=True,
                   termination='SIGTERM after all component and pool objects are released',
                   natural_process_teardown_tested=False)
    state = STATE_COMMAND.replace('media.hwcodec|', 'media.hwcodec|media.audio.qc.codec|mediaserver|')

    def call(label, *arguments):
        result = subprocess.run([str(args.adb), '-s', 'ca10ede3', *arguments],
                                capture_output=True, timeout=40)
        (work / (label + '.log')).write_bytes(result.stdout + result.stderr)
        return result

    prepared = False
    try:
        before = call('before-state', 'shell', state)
        before.check_returncode()
        receipt['before'] = identities(before.stdout)
        assert receipt['before']['selinux'] == 'Enforcing'
        boot_before = call('boot-before', 'shell', 'cat /proc/sys/kernel/random/boot_id')
        boot_before.check_returncode()
        call('prepare', 'shell', 'mkdir ' + remote).check_returncode()
        prepared = True
        expected = {}
        for kind, entry in build['outputs'].items():
            binary = Path(entry['path'])
            assert sha(binary) == entry['sha256']
            local = work / binary.name
            shutil.copyfile(binary, local)
            path = str(local)
            if args.adb.suffix == '.exe':
                path = subprocess.check_output(['wslpath', '-w', path], text=True).strip()
            call('push-' + kind, 'push', path, remote + '/' + binary.name).check_returncode()
            expected[remote + '/' + binary.name] = entry['sha256']
        hashes = call('uploaded', 'shell', 'sha256sum ' + ' '.join(expected))
        hashes.check_returncode()
        actual = {name: digest for digest, name in
                  (line.split() for line in hashes.stdout.decode().splitlines())}
        assert actual == expected
        call('executable', 'shell', 'chmod 755 ' + remote + '/' + profile['bootstrap']).check_returncode()
        command = f'''env LD_LIBRARY_PATH={remote}:/vendor/lib64:/system/lib64 {remote}/{profile['bootstrap']} --pool-probe > {remote}/result.log 2>&1 &
probe_pid=$!
ready=0
for attempt in $(seq 1 150); do
    if grep -qF 'QTI_POOL_PROBE: components and pools released; ready for SIGTERM' {remote}/result.log; then
        ready=1
        break
    fi
    if ! kill -0 "$probe_pid" 2>/dev/null; then break; fi
    sleep 0.1
done
if [ "$ready" = 1 ]; then kill -TERM "$probe_pid"; else kill -KILL "$probe_pid" 2>/dev/null; fi
wait "$probe_pid"
probe_exit=$?
cat {remote}/result.log
echo "QTI_POOL_RUNNER: pid=$probe_pid ready=$ready exit=$probe_exit"
[ "$ready" = 1 ] && [ "$probe_exit" = 143 ]
'''
        result = call('probe', 'shell', command)
        output = result.stdout.decode(errors='replace')
        receipt['exit_code'] = result.returncode
        receipt['components'] = {
            name: bool(re.search(r'QTI_PAYLOAD: alac_hidl_pool=' + re.escape(name) +
                                r' status=0 id=\d+ allocated=0\b', output))
            for name in ('c2.qti.alac.sw.decoder', 'c2.qti.alac.hw.decoder')}
        receipt['planned_service_stop_passed'] = result.returncode == 0 and bool(
            re.search(r'QTI_POOL_RUNNER: pid=\d+ ready=1 exit=143\b', output))
        after = call('after-state', 'shell', state)
        after.check_returncode()
        receipt['after'] = identities(after.stdout)
        boot_after = call('boot-after', 'shell', 'cat /proc/sys/kernel/random/boot_id')
        boot_after.check_returncode()
        receipt['services_and_boot_unchanged'] = (receipt['before'] == receipt['after']
                                                 and boot_before.stdout == boot_after.stdout)
        receipt['passed'] = (all(receipt['components'].values())
                             and receipt['planned_service_stop_passed']
                             and receipt['services_and_boot_unchanged'])
    except BaseException as error:
        receipt['error'] = repr(error)
        raise
    finally:
        if prepared:
            cleanup = call('cleanup', 'shell', 'rm -f ' + remote + '/' + profile['bootstrap'] +
                           ' ' + remote + '/' + profile['payload'] + ' ' + remote + '/result.log; rmdir ' + remote)
            receipt['remote_files_removed'] = cleanup.returncode == 0
            receipt['passed'] = receipt['passed'] and receipt['remote_files_removed']
        (work / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k: v for k, v in receipt.items() if k not in ('source_hashes', 'before', 'after')}, indent=2))
    if not receipt['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
