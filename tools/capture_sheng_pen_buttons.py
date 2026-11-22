#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read only the pen's evdev endpoints during a user-operated button trial."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time


def main():
    workspace = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=180)
    args = parser.parse_args()
    if not 10 <= args.seconds <= 600:
        parser.error('duration must be 10 to 600 seconds')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    adb = [str(workspace/'tools/platform-tools/adb.exe'), '-s', 'ca10ede3']

    def read(command):
        return subprocess.check_output([*adb, 'shell', command], timeout=20).decode().strip()

    if read('getprop ro.product.device') != 'sheng':
        raise RuntimeError('Expected the connected sheng tablet')
    caps = read('getevent -lp')
    nodes = {}
    names = {'Xiaomi Focus Pen Pro', 'Xiaomi Focus Pen Pro Keyboard',
             'Xiaomi Focus Pen Pro Mouse', 'NVTCapacitivePenP81c'}
    for block in re.split(r'(?=^add device \d+:)', caps, flags=re.MULTILINE):
        node = re.search(r'^add device \d+: (/dev/input/event\d+)\s*$', block, re.MULTILINE)
        name = re.search(r'name:\s*"([^"]+)"', block)
        if node and name and name[1] in names:
            if name[1] in nodes:
                raise RuntimeError('Ambiguous pen endpoint')
            nodes[name[1]] = node[1]
    if 'Xiaomi Focus Pen Pro Keyboard' not in nodes:
        raise RuntimeError('Connected Pro keyboard endpoint is required')
    receipt = dict(started_utc=datetime.now(timezone.utc).isoformat(), nodes=nodes,
                   serial='ca10ede3', read_only=True, screenshots_taken=False,
                   completed=False, events={}, exit_codes={})
    streams, processes = {}, {}
    runtime_stream = None
    runtime_process = None
    try:
        for name, node in nodes.items():
            stream = (out/(name.replace(' ', '-')+'.log')).open('wb')
            streams[name] = stream
            processes[name] = subprocess.Popen(
                [*adb, 'shell', f'timeout {args.seconds} getevent -lt {node}'],
                stdout=stream, stderr=subprocess.STDOUT)
        runtime_stream = (out/'button-service.log').open('wb')
        runtime_process = subprocess.Popen([*adb, 'logcat', '-v', 'threadtime', '-T', '1',
            'ShengPenButtons:I', 'ShengStylus:I', '*:S'], stdout=runtime_stream, stderr=subprocess.STDOUT)
        print('CAPTURE_READY '+str(out), flush=True)
        deadline = time.monotonic()+args.seconds+15
        while any(p.poll() is None for p in processes.values()) and time.monotonic() < deadline:
            time.sleep(1)
        receipt['completed'] = all(p.poll() in (0, 124) for p in processes.values())
    finally:
        if runtime_process is not None:
            runtime_process.terminate()
            try:
                runtime_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                runtime_process.kill(); runtime_process.wait(timeout=5)
        if runtime_stream is not None:
            runtime_stream.close()
        for name, process in processes.items():
            if process.poll() is None:
                process.terminate()
            try:
                receipt['exit_codes'][name] = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                receipt['exit_codes'][name] = process.wait(timeout=5)
        for stream in streams.values():
            stream.close()
        for name in streams:
            content = (out/(name.replace(' ', '-')+'.log')).read_text(errors='replace')
            keys = [line for line in content.splitlines() if 'EV_KEY' in line or 'MSC_SCAN' in line]
            receipt['events'][name] = dict(keys=keys, syn_dropped=content.count('SYN_DROPPED'))
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        (out/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(dict(completed=receipt['completed'], output=str(out),
        events={name:dict(key_records=len(value['keys']),syn_dropped=value['syn_dropped'])
                for name,value in receipt['events'].items()}), indent=2))


if __name__ == '__main__':
    main()
