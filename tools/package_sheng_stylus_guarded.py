#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Guard native r65 staging with the same C-only swap and host reserves as the build."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from sheng_stylus_host_sample import read_host_sample
from sheng_stylus_evidence import qualified_build_record


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def main():
    tools = Path(__file__).resolve().parent
    workspace = tools.parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('guard', 'artifacts', 'runtime-inputs', 'work', 'report', 'host-sample-dir'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--host-sample-id', required=True)
    args = parser.parse_args()
    report = args.report.resolve(strict=True)
    if (report/'guard-status.json').exists():
        raise ValueError('The packaging guard receipt must not be overwritten')
    status = dict(started_utc=datetime.now(timezone.utc).isoformat(), completed=False,
                  installed=False, c_drive_reserve=6*1024**3, host_commit_reserve=3*1024**3,
                  memory_max=6*1024**3, swap_max=20*1024**3,
                  guard_source_sha256=digest(Path(__file__)),
                  package_source_sha256=digest(tools/'package_sheng_stylus_service.py'))
    cgroup = None
    child = None
    lock = None

    def save():
        (report/'guard-status.json').write_text(json.dumps(status, indent=2)+'\n')

    def sample():
        return read_host_sample(args.host_sample_id, sample_directory=args.host_sample_dir)

    def stop_child():
        if child is not None and child.poll() is None:
            for sig, seconds in ((signal.SIGINT, 20), (signal.SIGTERM, 10), (signal.SIGKILL, 5)):
                try:
                    os.killpg(child.pid, sig)
                except ProcessLookupError:
                    break
                try:
                    child.wait(timeout=seconds)
                    break
                except subprocess.TimeoutExpired:
                    continue

    try:
        rom = Path('/root/sheng-lineage/lineage-24.0')
        guard = qualified_build_record(args.guard, workspace, rom)
        artifacts = json.loads(args.artifacts.read_text())
        if not (guard.get('qualified_module_build_passed') is True
                and guard.get('compiler_restored') is True and artifacts.get('passed') is True
                and artifacts.get('guard_sha256') == digest(args.guard)):
            raise ValueError('A qualified frozen-service build is required')
        lock = (rom/'out/.sheng-device-modules.lock').open('a')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        builder = rom/'out/host/linux-x86/bin/soong_build'
        with builder.open('rb') as stream:
            header = stream.read(4)
        if builder.with_name(builder.name+'.sheng-real').exists() or header != b'\x7fELF':
            raise ValueError('The original Soong compiler must be restored before packaging')
        status['soong_compiler_sha256_before'] = digest(builder)
        subprocess.run(['python3', tools/'prepare_sheng_stylus_swap.py', '--work', report], check=True)
        status['swap_policy'] = json.loads((report/'swap-priority.json').read_text())
        initial = sample()
        if initial['c_free_bytes'] < 10*1024**3 or initial['free_commit_bytes'] < 8*1024**3:
            raise ValueError('Insufficient C: space or host commit reserve to start native staging')
        status['initial'] = initial
        cgroup = Path('/sys/fs/cgroup')/('sheng-stylus-package-'+str(os.getpid()))
        if 'memory' not in (cgroup.parent/'cgroup.controllers').read_text().split():
            raise ValueError('The native guest memory controller is required')
        if 'memory' not in (cgroup.parent/'cgroup.subtree_control').read_text().split():
            (cgroup.parent/'cgroup.subtree_control').write_text('+memory')
        cgroup.mkdir()
        for name, value in (('memory.high', status['memory_max']), ('memory.max', status['memory_max']),
                            ('memory.swap.max', status['swap_max'])):
            (cgroup/name).write_text(str(value))
        command = ['python3', str(tools/'package_sheng_stylus_service.py')]
        for name in ('workspace', 'guard', 'artifacts', 'runtime-inputs', 'work'):
            value = workspace if name == 'workspace' else getattr(args, name.replace('-', '_'))
            command += ['--'+name, str(value)]
        command.append('--discard-verified-before-trees')
        status['command'] = command
        save()
        with (report/'package-output.log').open('w') as log:
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                preexec_fn=lambda: (cgroup/'cgroup.procs').write_text(str(os.getpid())))
            status['pid'] = child.pid
            while child.poll() is None:
                current = sample()
                current.update(guest_memory_bytes=int((cgroup/'memory.current').read_text()),
                               guest_swap_bytes=int((cgroup/'memory.swap.current').read_text()),
                               memory_events=(cgroup/'memory.events').read_text())
                status['latest_sample'] = current
                with (report/'resources.jsonl').open('a') as observations:
                    observations.write(json.dumps(current)+'\n')
                save()
                if (current['c_free_bytes'] < status['c_drive_reserve']
                        or current['free_commit_bytes'] < status['host_commit_reserve']):
                    status['stopped_reason'] = 'Host commit or C: space fell below the retained reserve'
                    stop_child()
                    break
                time.sleep(2)
            status['exit_code'] = child.wait()
        status['soong_compiler_sha256_after'] = digest(builder)
        if status['soong_compiler_sha256_after'] != status['soong_compiler_sha256_before']:
            raise ValueError('The original Soong compiler changed during packaging')
        if status['exit_code'] != 0 or status.get('stopped_reason'):
            raise ValueError('Native staging ended without qualification')
        manifest = workspace/'artifacts/system-hardware-followup-sheng-r65/build-result.json'
        sealed = json.loads(manifest.read_text())
        if sealed['revision'] != 65 or sealed.get('native_c_staging') is not True:
            raise ValueError('The expected sealed native-staged candidate was not published')
        status.update(completed=True, package_manifest_sha256=digest(manifest))
    except BaseException as error:
        status['error'] = repr(error)
        stop_child()
        if child is not None:
            status['exit_code'] = child.poll()
        raise
    finally:
        incomplete_cleanup = False
        if cgroup is not None and cgroup.exists():
            status['final_memory_events'] = (cgroup/'memory.events').read_text()
            remaining = (cgroup/'cgroup.procs').read_text().split()
            status['remaining_owned_processes'] = remaining
            if not remaining:
                cgroup.rmdir()
            elif status['completed']:
                status.update(completed=False, error='Owned packaging descendants remain after successful exit')
                incomplete_cleanup = True
        status['finished_utc'] = datetime.now(timezone.utc).isoformat()
        save()
        if lock is not None:
            lock.close()
        print('Packaging evidence: '+str(report), flush=True)
        if incomplete_cleanup:
            raise RuntimeError(status['error'])


if __name__ == '__main__':
    main()
