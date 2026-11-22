#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the normal module builder with bounded guest memory and a host reserve."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import tempfile
from sheng_stylus_host_sample import read_host_sample

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--phase', choices=('modules', 'freeze-api', 'graph'), default='modules')
parser.add_argument('--resident-gib', type=int, choices=(7, 9, 10), default=7)
parser.add_argument('--poll-seconds', type=int, choices=range(1, 11), default=2)
sample_source = parser.add_mutually_exclusive_group()
sample_source.add_argument('--host-sample', type=Path)
sample_source.add_argument('--host-sample-dir', type=Path)
parser.add_argument('--host-sample-id')
parser.add_argument('--with-media', action='store_true')
options = parser.parse_args()
if options.phase == 'freeze-api' and options.with_media:
    parser.error('API freezing is a separate source operation')
if bool(options.host_sample or options.host_sample_dir) != bool(options.host_sample_id):
    parser.error('A native sample source and --host-sample-id must be supplied together')
targets = {
    'modules': ['ShengStylus', 'vendor.lineage.sheng.stylus-service',
                'sheng_stylus_control_test', 'selinux_policy',
                'framework_compatibility_matrix.device.xml'],
    'freeze-api': ['vendor.lineage.sheng.stylus-freeze-api'],
    'graph': ['nothing'],
}[options.phase]
if options.with_media and options.phase == 'modules':
    targets += ['sheng-qti-codec2-bootstrap', 'libsheng_qti_codec2_service']

TOOLS = Path(__file__).resolve().parent
parent = TOOLS.parents[3]/'reports/device/20261114-stylus-service'
parent.mkdir(parents=True, exist_ok=True)
WORK = Path(tempfile.mkdtemp(prefix='normal-module-build-', dir=parent))
(WORK/'guard-source.py').write_bytes(Path(__file__).read_bytes())
(WORK/'host-sample-source.py').write_bytes((TOOLS/'sheng_stylus_host_sample.py').read_bytes())
os.environ.update(LANG='C.UTF-8', LC_ALL='C.UTF-8')
ROM = Path('/root/sheng-lineage/lineage-24.0')
builder = ROM/'out/host/linux-x86/bin/soong_build'
if builder.with_name(builder.name+'.sheng-real').exists(): raise RuntimeError('Compiler wrapper still owned')
if builder.read_bytes()[:4] != b'\x7fELF': raise RuntimeError('Original analyzer was not restored')
processes = subprocess.check_output(['ps', '-eo', 'comm='], text=True).splitlines()
if any(name.strip() in ('soong_build', 'ninja') for name in processes): raise RuntimeError('Another build is active')

def host():
    if options.host_sample or options.host_sample_dir:
        return read_host_sample(options.host_sample_id, sample_path=options.host_sample,
                                sample_directory=options.host_sample_dir)
    command = ['/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe',
               '-NoProfile', '-NonInteractive', '-Command',
               '(Get-CimInstance Win32_OperatingSystem).FreeVirtualMemory']
    value = subprocess.check_output(command, timeout=30, text=True).strip()
    return dict(date_utc=datetime.now(timezone.utc).isoformat(),
                free_commit_bytes=int(value)*1024, c_free_bytes=shutil.disk_usage('/mnt/c').free)

subprocess.run(['python3', TOOLS/'prepare_sheng_stylus_swap.py', '--work', WORK], check=True)
initial = host()
initial['guest_vm_memory_bytes'] = int(next(line.split()[1] for line in
    Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemTotal:'))) * 1024
initial_commit_requirement = initial['guest_vm_memory_bytes'] + 4*1024**3
if initial['free_commit_bytes'] < initial_commit_requirement or initial['c_free_bytes'] < 10*1024**3:
    raise RuntimeError('Insufficient host reserve for the reviewed swap-backed analyzer configuration: '+str(initial))
if options.resident_gib*1024**3 + 512*1024**2 > initial['guest_vm_memory_bytes']:
    raise RuntimeError('The child resident limit must leave at least 512 MiB for the guest')
status = dict(started_utc=datetime.now(timezone.utc).isoformat(), initial=initial,
              supervisor_pid=os.getpid(),
              phase=options.phase, requested_targets=targets, with_media=options.with_media,
              poll_seconds=options.poll_seconds,
              guard_source_sha256=hashlib.sha256((WORK/'guard-source.py').read_bytes()).hexdigest(),
              host_sample_source_sha256=hashlib.sha256((WORK/'host-sample-source.py').read_bytes()).hexdigest(),
              host_sample_file=str(options.host_sample) if options.host_sample else None,
              host_sample_directory=str(options.host_sample_dir) if options.host_sample_dir else None,
              native_host_monitor=bool(options.host_sample or options.host_sample_dir),
              gomemlimit='12GiB', memory_high=options.resident_gib*1024**3,
              memory_max=options.resident_gib*1024**3,
              swap_max=20*1024**3, host_commit_reserve=3*1024**3,
              initial_commit_requirement_bytes=initial_commit_requirement,
              c_drive_reserve=6*1024**3, normal_phase_passed=False,
              normal_module_build_passed=False, graph_generation_passed=False,
              api_freeze_command_passed=False,
              full_product_build_passed=False, installed=False)
status['swap_policy'] = json.loads((WORK/'swap-priority.json').read_text())
status['incremental_analysis_requested'] = False
status['configuration_reason'] = ('Incremental 9 GiB analysis exhausted its 10 GiB resident + 2 GiB swap cgroup; '
    'explicit nonincremental analysis also reached the host commit reserve. Keep actual nonincremental mode, '
    f'bound resident memory to {options.resident_gib} GiB and permit 20 GiB of already-provisioned guest swap; '
    'the logical 12 GiB Go budget matches the retained successful full-product configuration. '
    'Do not prune product sources, change public code, or lower the host reserve.')
def save(): (WORK/'guard-status.json').write_text(json.dumps(status, indent=2)+'\n')
save()
subprocess.run(['python3', TOOLS/'prepare_sheng_stylus_product.py', WORK], check=True)
cgroup = Path('/sys/fs/cgroup')/('sheng-stylus-'+str(os.getpid()))
try:
    root = cgroup.parent
    if 'memory' not in (root/'cgroup.controllers').read_text().split():
        raise RuntimeError('Guest memory controller unavailable')
    if 'memory' not in (root/'cgroup.subtree_control').read_text().split():
        (root/'cgroup.subtree_control').write_text('+memory')
    cgroup.mkdir()
    for name, value in [('memory.high', status['memory_high']), ('memory.max', status['memory_max']),
                        ('memory.swap.max', status['swap_max'])]:
        (cgroup/name).write_text(str(value))
except Exception as error:
    status.update(exit_code=1, setup_error=str(error), compiler_restored=True)
    save()
    if cgroup.exists() and not (cgroup/'cgroup.procs').read_text().strip(): cgroup.rmdir()
    raise
environment = os.environ.copy()
environment.update(SHENG_SOONG_GOMEMLIMIT='12GiB', SHENG_SOONG_CPU_LIMIT='3', SHENG_BUILD_JOBS='3',
                   SOONG_INCREMENTAL_ANALYSIS='false')
if options.with_media: environment['SHENG_INCLUDE_MEDIA_SENSORS'] = '1'
command = ['bash', str(TOOLS/'build_sheng_pen_settings_product.sh'), *targets]
status['command'] = command
print('Guard work: '+str(WORK), flush=True)
with (WORK/'build-output.log').open('w') as log:
    child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                             env=environment, start_new_session=True,
                             preexec_fn=lambda: (cgroup/'cgroup.procs').write_text(str(os.getpid())))
    status['pid'] = child.pid; save()
    stopping = False
    try:
        while child.poll() is None:
            sample = host()
            sample['guest_memory_bytes'] = int((cgroup/'memory.current').read_text())
            sample['guest_swap_bytes'] = int((cgroup/'memory.swap.current').read_text())
            sample['effective_memory_limits'] = {name: int((cgroup/name).read_text())
                for name in ('memory.high', 'memory.max', 'memory.swap.max')}
            sample['memory_events'] = (cgroup/'memory.events').read_text()
            sample['memory_pressure'] = (cgroup/'memory.pressure').read_text()
            sample['guest_meminfo'] = [line for line in Path('/proc/meminfo').read_text().splitlines()
                                      if line.startswith(('MemTotal:', 'MemAvailable:', 'Cached:', 'SwapFree:'))]
            if 'analyzer_command' not in status:
                for value in (cgroup/'cgroup.procs').read_text().split():
                    process_cmdline = Path('/proc')/value/'cmdline'
                    try: args = process_cmdline.read_bytes().decode().strip('\0').split('\0')
                    except (FileNotFoundError, ProcessLookupError): continue
                    if args and 'soong_build' in args[0] and '--soong_variables' in args:
                        status['analyzer_pid'] = int(value)
                        status['analyzer_command'] = args
                        status['incremental_analysis_actual'] = '--incremental-build-actions' in args
                        if status['incremental_analysis_actual']:
                            status['stopped_reason'] = 'Requested nonincremental analysis was not applied to the actual analyzer'
                            stopping = True; os.killpg(child.pid, signal.SIGINT)
                        break
            if 'analyzer_pid' in status:
                try:
                    sample['analyzer_status'] = [line for line in
                        (Path('/proc')/str(status['analyzer_pid'])/'status').read_text().splitlines()
                        if line.startswith(('VmRSS:', 'VmSwap:', 'Threads:'))]
                except (FileNotFoundError, ProcessLookupError): pass
            with (WORK/'resources.jsonl').open('a') as output: output.write(json.dumps(sample)+'\n')
            status['latest_sample'] = sample; save()
            if stopping: break
            if sample['free_commit_bytes'] < status['host_commit_reserve'] or sample['c_free_bytes'] < status['c_drive_reserve']:
                status['stopped_reason'] = 'Host reserve fell below the reviewed threshold'
                stopping = True; os.killpg(child.pid, signal.SIGINT); break
            time.sleep(options.poll_seconds)
        if stopping:
            try: child.wait(timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGTERM); child.wait(timeout=30)
        else: child.wait()
    except BaseException as error:
        status['stopped_reason'] = 'Resource supervisor failed: '+repr(error)
        status['supervisor_error'] = repr(error)
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGINT)
            child.wait(timeout=60)
        raise
    finally:
        status['exit_code'] = child.poll()
        status['finished_utc'] = datetime.now(timezone.utc).isoformat()
        status['compiler_restored'] = not builder.with_name(builder.name+'.sheng-real').exists() and builder.read_bytes()[:4] == b'\x7fELF'
        status['memory_events'] = (cgroup/'memory.events').read_text()
        text = (WORK/'build-output.log').read_text(errors='replace')
        paths = [line.partition('Build evidence: ')[2] for line in text.splitlines() if line.startswith('Build evidence: ')]
        if paths:
            status['build_work'] = paths[-1]
            module_status = Path(paths[-1])/'status.json'
            if module_status.exists():
                status['module_status'] = json.loads(module_status.read_text())
                status['normal_phase_passed'] = status['module_status']['normal_module_build_passed']
                status['normal_module_build_passed'] = status['normal_phase_passed'] and options.phase == 'modules'
                status['graph_generation_passed'] = status['normal_phase_passed'] and options.phase == 'graph'
                status['api_freeze_command_passed'] = status['normal_phase_passed'] and options.phase == 'freeze-api'
        save()
        if not (cgroup/'cgroup.procs').read_text().strip(): cgroup.rmdir()
print(json.dumps(status, indent=2))
raise SystemExit(0 if status['normal_phase_passed'] else 1)
