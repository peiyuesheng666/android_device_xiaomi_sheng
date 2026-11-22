#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Inspect captured ATT requests and errors; do not infer missing traffic."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snoop', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--from-epoch', type=float, required=True)
    parser.add_argument('--to-epoch', type=float, required=True)
    args = parser.parse_args()
    if args.from_epoch > args.to_epoch:
        parser.error('Reversed time window')
    data = args.snoop.read_bytes()
    if data[:16] != b'btsnoop\0' + struct.pack('>II', 1, 1002):
        raise ValueError('Expected H4 btsnoop')
    position, count, short = 16, 0, 0
    drops, times, links, att = set(), [], {}, []
    while position < len(data):
        original, included, flags, dropped, timestamp = struct.unpack_from('>IIIIQ', data, position)
        position += 24
        packet = data[position:position + included]
        if len(packet) != included:
            raise ValueError('Truncated packet')
        position += included
        epoch = (timestamp - 0x00dcddb30f2f8000) / 1e6
        times.append(epoch)
        count += 1
        short += original != included
        drops.add(dropped)
        if len(packet) >= 15 and packet[:2] == bytes((4, 0x3e)) and packet[3] in (1, 0x0a) and packet[4] == 0:
            handle = struct.unpack_from('<H', packet, 5)[0]
            links[handle] = ':'.join(f'{b:02x}' for b in packet[9:15][::-1])
        elif len(packet) >= 7 and packet[:2] == bytes((4, 5)) and packet[3] == 0:
            links.pop(struct.unpack_from('<H', packet, 4)[0], None)
        if len(packet) < 9 or packet[0] != 2 or not args.from_epoch <= epoch <= args.to_epoch:
            continue
        raw_handle, acl_length, length, cid = struct.unpack_from('<HHHH', packet, 1)
        if (raw_handle >> 12) & 3 == 1 or cid != 4:
            continue
        payload = packet[9:]
        if acl_length != len(packet) - 5 or length != len(payload) or not payload:
            raise ValueError('Incomplete ATT packet')
        item = dict(epoch=epoch, utc=datetime.fromtimestamp(epoch, timezone.utc).isoformat(),
                    direction='in' if flags & 1 else 'out', connection=f'0x{raw_handle & 0xfff:04x}',
                    address=links.get(raw_handle & 0xfff), opcode=f'0x{payload[0]:02x}', hex=payload.hex())
        if payload[0] == 1 and len(payload) == 5:
            item.update(failed_opcode=f'0x{payload[1]:02x}', attribute=f'0x{int.from_bytes(payload[2:4], "little"):04x}',
                        error=f'0x{payload[4]:02x}')
        elif payload[0] in (0x0a, 0x0c, 0x12, 0x1b, 0x1d, 0x52) and len(payload) >= 3:
            item['attribute'] = f'0x{int.from_bytes(payload[1:3], "little"):04x}'
        att.append(item)
    report = dict(snoop_sha256=hashlib.sha256(data).hexdigest(), packets=count,
                  capture_from_epoch=min(times), capture_to_epoch=max(times),
                  window_from_epoch=args.from_epoch, window_to_epoch=args.to_epoch,
                  capture_covers_window=min(times) <= args.from_epoch and max(times) >= args.to_epoch,
                  shortened_packets=short, recorded_drops=sorted(drops), att=att,
                  limitation='This capture may be filtered; absence does not prove a request stayed on the host.')
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
