#!/usr/bin/env python3
"""Decode bounded DP write-entry traces; never equate them with MMIO readback."""
import argparse
import json
import re
from pathlib import Path

WRITE = re.compile(
    r'\s(\d+\.\d+):\s+hw_write:.*?bank="([^"]+)"\s+'
    r'off=(0x[0-9a-fA-F]+|\d+)\s+val=(0x[0-9a-fA-F]+|\d+)')
REGS = {
    'dp_link': {0: 'MAINLINK_CTRL', 4: 'STATE_CTRL', 8: 'CONFIGURATION_CTRL',
                16: 'SOFTWARE_MVID', 24: 'SOFTWARE_NVID',
                28: 'TOTAL_HOR_VER', 32: 'START_HOR_VER_FROM_SYNC',
                36: 'HSYNC_VSYNC_WIDTH_POLARITY', 40: 'ACTIVE_HOR_VER',
                44: 'MISC1_MISC0', 48: 'VALID_BOUNDARY', 52: 'VALID_BOUNDARY_2',
                76: 'TU', 552: 'SDP_CFG', 556: 'SDP_CFG2', 588: 'SDP_CFG3',
                **{768 + n * 4: f'GENERIC0_{n}' for n in range(10)}},
    'dp_p0': {16: 'TIMING_ENGINE_EN', 20: 'INTF_CONFIG',
              136: 'ASYNC_FIFO_CONFIG'},
}


def decode(text):
    events = []
    final = {}
    for match in WRITE.finditer(text):
        timestamp, bank, offset, value = match.groups()
        offset, value = int(offset, 0), int(value, 0)
        name = REGS.get(bank, {}).get(offset)
        if name is None:
            raise ValueError(f'Unexpected captured register: {bank}+{offset:#x}')
        key = f'{bank}.{name}'
        events.append({'time_s': float(timestamp), 'register': key,
                       'offset': hex(offset), 'value': hex(value)})
        final[key] = hex(value)
    return {
        'scope': 'Hardware-writer entry arguments only; not MMIO/wire readback',
        'write_events': len(events),
        'positive_write_coverage': bool(events),
        'clock_mn_write_coverage': all(
            f'dp_link.SOFTWARE_{name}' in final for name in ('MVID', 'NVID')),
        'events': events,
        'last_observed_arguments': final,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('trace', type=Path)
    args = p.parse_args()
    result = decode(args.trace.read_text(encoding='utf-8', errors='replace'))
    print(json.dumps(result, indent=2))
    return 0 if result['positive_write_coverage'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
