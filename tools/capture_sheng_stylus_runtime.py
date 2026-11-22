#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Observe the installed stylus service and real NVT input during a physical trial."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

from verify_sheng_stylus_runtime import APP, DAEMON

PEN_NODES = {'NVTCapacitivePenM80p': 8191, 'NVTCapacitivePenP81c': 16383}
# The real battery hall attributes omit trailing newlines. Frame each value
# explicitly so that it cannot merge with another hall value or a setting.
DOCK_COMMAND = (
    'for node in pen_hall3 pen_hall4; do '
    'value=$(cat /sys/class/qcom-battery/$node) || exit 1; '
    'printf \'%s\\n\' "$value"; done; '
)
STATE_COMMAND = (
    'getprop init.svc.vendor.sheng-stylus; pidof '+DAEMON+'; pidof '+APP+'; '
    'cat /sys/class/drm/card0-DSI-1/dpms; '
    + DOCK_COMMAND +
    'settings get system min_refresh_rate; settings get system peak_refresh_rate; '
    'cat /data/user_de/0/'+APP+'/files/pro-input-lease.json'
)


def observation_values(content):
    values = content.strip().splitlines()
    if (len(values) != 9 or values[3] not in ('On', 'Off')
            or any(value not in ('0', '1') for value in values[4:6])):
        raise ValueError('Unexpected observation layout or dock/display state')
    return values


def pen_nodes(capabilities):
    result = {}
    for block in re.split(r'(?=^add device \d+:)', capabilities, flags=re.MULTILINE):
        node = re.search(r'^add device \d+: (/dev/input/event\d+)\s*$', block, re.MULTILINE)
        name = re.search(r'^\s*name:\s*"([^"]+)"\s*$', block, re.MULTILINE)
        if not node or not name or name[1] not in PEN_NODES:
            continue
        pressure = re.search(r'\bABS_PRESSURE\s*:\s*value -?\d+, min 0, max (\d+),', block)
        if (pressure is None or int(pressure[1]) != PEN_NODES[name[1]]
                or not all(re.search(r'\b'+axis+r'\s*:', block) for axis in ('ABS_X', 'ABS_Y'))
                or 'INPUT_PROP_DIRECT' not in block or name[1] in result):
            raise ValueError('Unexpected NVT pen capabilities or duplicate endpoint')
        result[name[1]] = node[1]
    if set(result) != set(PEN_NODES) or len(set(result.values())) != len(PEN_NODES):
        raise ValueError('Both distinct real NVT pen endpoints are required')
    return result


def value_limits(values):
    return dict(count=len(values), distinct=len(set(values)), minimum=min(values), maximum=max(values)) if values else dict(count=0, distinct=0)


def main():
    workspace = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', type=Path, default=workspace/'tools/platform-tools/adb.exe')
    parser.add_argument('--runtime', type=Path, required=True, help='Successful installed-service readback receipt')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=180, help='Capture duration, 1 to 600 seconds')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 600:
        parser.error('--seconds must be between 1 and 600')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    streams, processes = {}, {}
    commands = []
    receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), serial='ca10ede3',
                   capture_completed=False, protocol_commands_sent=False,
                   input_ownership_changed=False, native_service_restarted=False,
                   user_writing_accepted=False, native_crash_auto_recovery_passed=False)

    def call(label, command, checked=True):
        argv = [str(args.adb), '-s', 'ca10ede3', 'shell', command]
        result = subprocess.run(argv, capture_output=True, timeout=20)
        (output/(label+'.stdout')).write_bytes(result.stdout)
        (output/(label+'.stderr')).write_bytes(result.stderr)
        commands.append(dict(argv=argv, returncode=result.returncode, output=label))
        (output/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
        if checked:
            result.check_returncode()
        return result

    def identity(label):
        values = call(label, 'getprop ro.product.device; getprop ro.boot.slot_suffix; '
                      'getenforce; uname -r; cat /proc/sys/kernel/random/boot_id').stdout.decode().strip().splitlines()
        if len(values) != 5 or values[:4] != ['sheng', '_a', 'Enforcing', '5.15.220-gf9ca2b71f672']:
            raise ValueError('Unexpected live device, kernel, slot or SELinux state')
        return dict(zip(('device', 'slot', 'selinux', 'kernel', 'boot_id'), values))

    try:
        qualification_bytes = args.runtime.read_bytes()
        qualification = json.loads(qualification_bytes)
        if not (qualification.get('passed') is True and qualification.get('installed') is True
                and qualification.get('serial') == 'ca10ede3'
                and qualification.get('current_boot_processes_stable') is True
                and qualification.get('installed_contexts_verified') is True):
            raise ValueError('A successful installed-service readback is required')
        receipt['runtime_receipt_sha256'] = hashlib.sha256(qualification_bytes).hexdigest()
        receipt['before'] = identity('before-state')
        if receipt['before']['boot_id'] != qualification['after']['boot_id']:
            raise ValueError('Requalify the installed service after a real reboot')
        capabilities = call('input-capabilities', 'getevent -lp').stdout.decode()
        nodes = pen_nodes(capabilities)
        receipt['nodes'] = nodes
        initial = observation_values(call('initial-observation', STATE_COMMAND).stdout.decode())
        if (initial[:3] != ['running', str(qualification['processes']['daemon']['pid']),
                                   str(qualification['processes']['app']['pid'])]):
            raise ValueError('The qualified service or application restarted before capture')
        receipt['refresh_settings_before'] = initial[6:8]
        for name, node in nodes.items():
            streams[name] = (output/(name+'-events.txt')).open('wb')
            command = 'timeout '+str(args.seconds+10)+' getevent -lt '+node
            processes[name] = subprocess.Popen([str(args.adb), '-s', 'ca10ede3', 'shell', command],
                                               stdout=streams[name], stderr=subprocess.STDOUT)
        print('Read-only NVT capture ready: '+str(output), flush=True)
        started = time.monotonic()
        end = started+args.seconds
        next_display = started
        with (output/'observations.jsonl').open('w') as observations:
            while time.monotonic() < end and not (output/'STOP').exists():
                if any(process.poll() is not None for process in processes.values()):
                    raise ValueError('An owned input observer exited before capture completion')
                result = subprocess.run([str(args.adb), '-s', 'ca10ede3', 'shell', STATE_COMMAND],
                                        capture_output=True, timeout=20)
                values = result.stdout.decode(errors='replace').strip().splitlines()
                sample = dict(date_utc=datetime.now(timezone.utc).isoformat(),
                              elapsed_seconds=round(time.monotonic()-started, 3),
                              returncode=result.returncode, values=values,
                              stderr=result.stderr.decode(errors='replace'))
                observations.write(json.dumps(sample)+'\n')
                observations.flush()
                observation_values(result.stdout.decode(errors='replace'))
                if result.returncode != 0 or values[:3] != initial[:3]:
                    raise ValueError('The live service/app or observation transport changed during capture')
                if time.monotonic() >= next_display:
                    call('display-'+str(int(time.monotonic()-started)), 'dumpsys display')
                    next_display = time.monotonic()+5
                time.sleep(min(0.75, max(0, end-time.monotonic())))
        receipt['elapsed_seconds'] = round(time.monotonic()-started, 3)
        receipt['capture_stopped_by_marker'] = (output/'STOP').exists()
        final = observation_values(call('final-observation', STATE_COMMAND).stdout.decode())
        if final[:3] != initial[:3]:
            raise ValueError('The observed native service or application restarted')
        receipt['refresh_settings_after'] = final[6:8]
        receipt['refresh_settings_unchanged'] = final[6:8] == initial[6:8]
        call('final-input-state', 'dumpsys input')
        call('final-boot-logcat', 'logcat -b all -d -v threadtime')
        call('final-controller-log', 'dmesg')
        receipt['after'] = identity('after-state')
        if receipt['after'] != receipt['before'] or args.runtime.read_bytes() != qualification_bytes:
            raise ValueError('The device or qualification changed during capture')
        receipt['capture_completed'] = True
    except BaseException as error:
        receipt['error'] = repr(error)
        raise
    finally:
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for stream in streams.values():
            stream.close()
        event_summary = {}
        for name in streams:
            content = (output/(name+'-events.txt')).read_text(errors='replace')
            values = [int(value, 16) for value in re.findall(r'\bABS_PRESSURE\s+([0-9a-fA-F]+)\s*$', content, re.MULTILINE)]
            event_summary[name] = dict(pressure=value_limits(values),
                                      pressure_values_in_range=all(0 <= value <= PEN_NODES[name] for value in values),
                                      syn_dropped=content.count('SYN_DROPPED'))
        receipt['real_nvt_input'] = event_summary
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        (output/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(dict(capture_completed=True, real_nvt_input=event_summary,
                         user_writing_accepted=False, output=str(output)), indent=2))


if __name__ == '__main__':
    main()
