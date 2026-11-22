#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Increase resident memory only for a verified guarded analyzer with host headroom."""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import subprocess
from sheng_stylus_host_sample import read_host_sample

parser = argparse.ArgumentParser()
parser.add_argument('--guard', type=Path, required=True)
parser.add_argument('--resident-gib', type=int, choices=[9, 10, 11], default=9)
args = parser.parse_args()
guard_path = args.guard.resolve(strict=True)
guard = json.loads(guard_path.read_text())
if 'exit_code' in guard or guard.get('incremental_analysis_actual') is not False:
    raise RuntimeError('Expected a live, verified nonincremental analysis')
if (guard.get('swap_policy', {}).get('policy') != 'C-only'
        or guard.get('swap_policy', {}).get('e_drive_swap_allowed') is not False):
    raise RuntimeError('Resident adjustment requires a verified C-only swap build')
child = guard['pid']
command = (Path('/proc')/str(child)/'cmdline').read_bytes().decode().strip('\0').split('\0')
if command != guard['command']:
    raise RuntimeError('Guarded child identity changed')
groups = [path for path in Path('/sys/fs/cgroup').glob('sheng-stylus-*')
          if str(child) in (path/'cgroup.procs').read_text().split()]
if len(groups) != 1: raise RuntimeError('Guarded child cgroup is ambiguous or missing')
cgroup = groups[0]
analyzer = guard['analyzer_pid']
if str(analyzer) not in (cgroup/'cgroup.procs').read_text().split():
    raise RuntimeError('Recorded analyzer no longer belongs to the guarded build')
actual = (Path('/proc')/str(analyzer)/'cmdline').read_bytes().decode().strip('\0').split('\0')
if actual != guard['analyzer_command']: raise RuntimeError('Analyzer identity changed')
before = {name: int((cgroup/name).read_text()) for name in ('memory.high', 'memory.max', 'memory.swap.max')}
previous_gib = {9: 7, 10: 9, 11: 10}[args.resident_gib]
if before != {'memory.high': previous_gib*1024**3, 'memory.max': previous_gib*1024**3, 'memory.swap.max': 20*1024**3}:
    raise RuntimeError('Unexpected prior memory configuration')
if guard.get('native_host_monitor'):
    host_sample = read_host_sample(guard['initial']['identity'],
        sample_path=Path(guard['host_sample_file']) if guard.get('host_sample_file') else None,
        sample_directory=Path(guard['host_sample_directory']) if guard.get('host_sample_directory') else None)
    sample_time = datetime.fromisoformat(host_sample['date_utc'].replace('Z', '+00:00'))
    age = datetime.now(timezone.utc).timestamp() - sample_time.timestamp()
    if (host_sample['identity'] != guard['initial']['identity']
            or host_sample['monitor_pid'] != guard['initial']['monitor_pid'] or not -3 <= age <= 10):
        raise RuntimeError('Native host sample changed identity or became stale')
    free = host_sample['free_commit_bytes']
else:
    free = int(subprocess.check_output([
        '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe', '-NoProfile', '-NonInteractive',
        '-Command', '(Get-CimInstance Win32_OperatingSystem).FreeVirtualMemory'], text=True, timeout=30).strip())*1024
guest_total = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                       if line.startswith('MemTotal:'))) * 1024
if args.resident_gib*1024**3 + 512*1024**2 > guest_total:
    raise RuntimeError('The requested resident limit must leave at least 512 MiB for the guest')
if args.resident_gib == 11 and not (11*1024**3 + 512*1024**2 <= guest_total <= 12*1024**3):
    raise RuntimeError('The 11 GiB adjustment requires the backed-up 12 GiB whole-VM memory profile')
# The fixed 12 GiB VM has already committed its host memory. This adjustment
# changes residency inside that bound, retaining the original 3 GiB stop reserve.
required_gib = {9: 7, 10: 5, 11: 4}[args.resident_gib]
if free < required_gib*1024**3:
    raise RuntimeError('Host cannot retain the 3 GiB stop reserve and reviewed growth margin')
receipt_path = guard_path.parent/{9: 'memory-resident-adjustment.json',
                                 10: 'memory-resident-adjustment-2.json',
                                 11: 'memory-resident-adjustment-3.json'}[args.resident_gib]
if receipt_path.exists(): raise RuntimeError('Adjustment receipt already exists')
receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), cgroup=str(cgroup),
    analyzer_pid=analyzer, analyzer_command=actual, free_commit_bytes=free, before=before,
    guest_vm_memtotal_bytes=guest_total, host_commit_stop_reserve_bytes=guard['host_commit_reserve'],
    native_host_monitor=guard.get('native_host_monitor', False),
    requested_resident_bytes=args.resident_gib*1024**3, required_free_commit_bytes=required_gib*1024**3,
    complete=False,
    reason=('The verified analyzer spends substantial time paging; allow a bounded increase '
            'only with the reviewed host headroom, keeping Go, swap, public code and the 3 GiB stop reserve unchanged'))
receipt_path.write_text(json.dumps(receipt, indent=2)+'\n')
(cgroup/'memory.max').write_text(str(args.resident_gib*1024**3))
(cgroup/'memory.high').write_text(str(args.resident_gib*1024**3))
receipt.update(complete=True, after={name: int((cgroup/name).read_text()) for name in before})
receipt_path.write_text(json.dumps(receipt, indent=2)+'\n')
print(json.dumps(receipt, indent=2))
