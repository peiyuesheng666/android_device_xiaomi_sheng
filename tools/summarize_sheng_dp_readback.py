#!/usr/bin/env python3
"""Decode bounded DP readbacks, without inferring visual or wire correctness."""
import argparse
import json
from pathlib import Path
import re

OFFSETS = (0, 4, 8, 16, 24, 44, 28, 32, 36, 40, 48, 52, 76,
           552, 556, 588, 768, 772, 792)
PATTERN = re.compile(r'\[\s*([\d.]+)\].*sheng_dp_rb link off=0x([0-9a-f]+) value=0x([0-9a-f]+)')


def decode(text, since=0.0):
    groups, current = [], []
    for line in text.splitlines():
        match = PATTERN.search(line)
        if not match:
            continue
        stamp, off, val = match.groups()
        if float(stamp) < since:
            continue
        off, val = int(off, 16), int(val, 16)
        if off == 0 and current:
            groups.append(current)
            current = []
        current.append((float(stamp), off, val))
    if current:
        groups.append(current)
    result = []
    for group in groups:
        regs = {off: val for _, off, val in group}
        complete = tuple(off for _, off, _ in group) == OFFSETS
        active = regs.get(40, 0)
        result.append(dict(time=group[0][0], complete=complete,
                           width=active & 0xffff, height=active >> 16,
                           registers={hex(off): hex(val) for off, val in regs.items()}))
    return dict(scope='DP register snapshots; not receiver, visual, or wire proof',
                snapshots=result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--since', type=float, default=0.0,
                        help='Kernel log timestamp boundary, NOT /proc/uptime (suspend clocks differ)')
    args = parser.parse_args()
    print(json.dumps(decode(args.input.read_text(), args.since), indent=2))
