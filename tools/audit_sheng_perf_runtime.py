#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read installed perf mappings and power state without changing device controls."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
import xml.etree.ElementTree as ET


def run(command):
    result = subprocess.run(command, text=True, encoding='utf-8',
                            errors='replace', capture_output=True, timeout=45)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.replace('\r\n', '\n')


def mappings(directory):
    """Apply Qualcomm's target override by resource key; retain disabled entries."""
    result = {}
    for group, files in (
        ('resource', ('commonresourceconfigs.xml', 'targetresourceconfigs.xml')),
        ('sysnode', ('commonsysnodesconfigs.xml', 'targetsysnodesconfigs.xml')),
    ):
        for filename in files:
            root = ET.parse(directory / filename).getroot()
            for entry in root.iter():
                attributes = entry.attrib
                if group == 'resource' and {'MajorValue', 'MinorValue'} <= attributes.keys():
                    key = (group, int(attributes['MajorValue'], 0),
                           int(attributes['MinorValue'], 0))
                elif group == 'sysnode' and 'Idx' in attributes:
                    key = (group, int(attributes['Idx'], 0))
                else:
                    continue
                record = result.setdefault(key, {'key': list(key), 'sources': []})
                record.update(attributes)
                record['sources'].append(filename)
    return list(result.values())


SNAPSHOT = r'''
uname -r
getprop ro.build.fingerprint
getprop sys.boot_completed
getprop vendor.post_boot.parsed
getenforce
cat /proc/sys/kernel/random/boot_id
for p in /sys/devices/system/cpu/qcom_lpm/parameters/* /sys/power/mem_sleep /sys/kernel/msm_performance/parameters/core_ctl_register /sys/kernel/msm_performance/notify/aggr_big_nr /sys/kernel/msm_performance/notify/aggr_top_load /sys/kernel/msm_performance/notify/top_load_cluster /sys/kernel/msm_performance/notify/curr_cap_cluster /sys/devices/system/cpu/cpufreq/policy*/related_cpus /sys/devices/system/cpu/cpufreq/policy*/scaling_governor /sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq /sys/devices/system/cpu/cpufreq/policy*/scaling_min_freq /sys/devices/system/cpu/cpufreq/policy*/scaling_max_freq /sys/devices/system/cpu/cpufreq/policy*/scaling_available_frequencies /sys/devices/system/cpu/cpu*/cpuidle/state*/name /sys/devices/system/cpu/cpu*/cpuidle/state*/time /sys/devices/system/cpu/cpu*/cpuidle/state*/usage /sys/devices/system/cpu/cpu*/cpuidle/state*/disable /sys/class/power_supply/battery/current_now /sys/class/power_supply/battery/voltage_now /sys/class/power_supply/battery/temp; do
    if [ -f "$p" ]; then
        printf '\nNODE %s\n' "$p"
        cat "$p" 2>&1
    fi
done
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', type=Path, required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    work = args.output.resolve()
    work.mkdir(parents=True, exist_ok=False)
    adb = [str(args.adb.resolve(strict=True)), '-s', args.serial]
    if run(adb + ['get-state']).strip() != 'device':
        raise RuntimeError('Selected device is not available')
    if run(adb + ['shell', 'getprop ro.product.device']).strip() != 'sheng':
        raise RuntimeError('Selected device is not sheng')
    def host_destination(path):
        if os.name != 'nt' and args.adb.suffix.lower() == '.exe':
            return run(['wslpath', '-w', str(path)]).strip()
        return str(path)
    run(adb + ['pull', '/vendor/etc/perf', host_destination(work / 'perf')])
    run(adb + ['pull', '/vendor/etc/powerhint.xml', host_destination(work / 'powerhint.xml')])
    records = mappings(work / 'perf')
    paths = sorted({record['Node'] for record in records
                    if record.get('Supported', 'yes').lower() != 'no'
                    and 'Node' in record})
    paths = [path for path in paths if re.fullmatch(r'/(?:sys|proc|dev)/[A-Za-z0-9_./-]+', path)]
    # Report metadata only: some perf nodes are blocking event or device files.
    commands = []
    for index, path in enumerate(paths):
        quoted = shlex.quote(path)
        commands.append(f"printf '\\nCHECK {index}\\n'; "
                        f"if [ -e {quoted} ]; then ls -ldZ {quoted}; "
                        f"else printf 'MISSING\\n'; fi")
    metadata = run(adb + ['shell', '\n'.join(commands)])
    (work / 'node-metadata.txt').write_text(metadata, encoding='utf-8')
    checks = {}
    for match in re.finditer(r'\nCHECK (\d+)\n(.*?)(?=\nCHECK |\Z)', metadata, re.S):
        checks[paths[int(match[1])]] = match[2].strip()
    for record in records:
        if record.get('Supported', 'yes').lower() == 'no':
            record['runtime_status'] = 'disabled_in_shipping_config'
        elif record.get('Node') in checks:
            status = checks[record['Node']]
            record['runtime_status'] = 'missing' if status == 'MISSING' else 'present'
            record['runtime_metadata'] = status
        else:
            record['runtime_status'] = 'non_path_or_dynamic_mapping_requires_consumer_check'
    samples = []
    for index in range(2):
        sample = run(adb + ['shell', SNAPSHOT])
        (work / f'power-snapshot-{index}.txt').write_text(sample, encoding='utf-8')
        samples.append(sample)
        if index == 0:
            time.sleep(3)
    boot_ids = [re.search(r'(?m)^[a-f0-9-]{36}$', sample) for sample in samples]
    if not all(boot_ids) or boot_ids[0][0] != boot_ids[1][0]:
        raise RuntimeError('Device boot changed while collecting the audit')
    files = sorted((work / 'perf').glob('*.xml')) + [work / 'powerhint.xml']
    report = {
        'date_utc': datetime.now(timezone.utc).isoformat(),
        'serial': args.serial,
        'kernel_release': samples[0].splitlines()[0],
        'boot_id': boot_ids[0][0],
        'read_only': True,
        'configuration_sha256': {str(path.relative_to(work)): hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in files},
        'effective_resource_mappings': records,
        'missing_paths': sorted({record['Node'] for record in records
                                if record['runtime_status'] == 'missing'}),
        'limits': ['Node existence does not prove semantics, HAL-domain access, or hint release.',
                   'Dynamic resource expansion and actual selected hints require consumer inspection.',
                   'ADB activity is not an idle power acceptance measurement.'],
    }
    (work / 'audit.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'kernel_release': report['kernel_release'], 'resources': len(records),
                      'missing_paths': report['missing_paths'], 'output': str(work)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
