#!/usr/bin/env python3
"""Summarize recorded power/data role transactions without changing a USB port."""
import argparse
import json
from pathlib import Path
import re


def analyze(text):
    swaps = []
    current = None
    for number, line in enumerate(text.splitlines(), 1):
        timestamp = re.search(r'\[\s*([0-9.]+)/', line)
        if not timestamp:
            continue
        seconds = float(timestamp[1])
        control = re.search(r'(sync_write|async_write): CONTROL: ((?:[0-9a-fA-F]{2} ?){8})', line)
        if control:
            command = int.from_bytes(bytes.fromhex(control[2]), 'little')
            if current is not None:
                current['next_command'] = hex(command)
                current['next_command_line'] = number
                current = None
            opcode = command & 255
            if opcode in (0x09, 0x0b):
                current = dict(line=number, timestamp=seconds, command=hex(command),
                               operation='SET_UOR' if opcode == 0x09 else 'SET_PDR', cci=[])
                swaps.append(current)
        cci = re.search(r'(notify|read): CCI: ((?:[0-9a-fA-F]{2} ?){4})', line)
        if cci and current is not None:
            value = int.from_bytes(bytes.fromhex(cci[2]), 'little')
            current['cci'].append(dict(line=number, elapsed=round(seconds-current['timestamp'], 6),
                                       origin=cci[1], value=hex(value), busy=bool(value & (1 << 28)),
                                       error=bool(value & (1 << 30)),
                                       command_complete=bool(value & (1 << 31))))
    for swap in swaps:
        complete = [item for item in swap['cci'] if item['command_complete'] and not item['busy']]
        if complete:
            # Command completion does not prove the physical role actually changed.
            swap['result'] = ('command_completed_with_error' if complete[0]['error']
                              else 'command_completed_check_role_separately')
            swap['completion_seconds'] = complete[0]['elapsed']
        elif any(item['busy'] for item in swap['cci']):
            swap['result'] = 'busy_without_recorded_completion'
        else:
            swap['result'] = 'no_recorded_completion'
        swap['followed_by_ppm_reset'] = swap.get('next_command') == '0x1'
    return dict(swaps=swaps, note='Only recorded CCI is classified; truncated logs, firmware cause, actual role and output watts require separate evidence.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.log.read_bytes()
    encoding = 'utf-16' if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8-sig'
    report = analyze(raw.decode(encoding))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(transactions=len(report['swaps']), output=str(args.output))))
