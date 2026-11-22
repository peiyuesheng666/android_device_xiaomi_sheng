#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Review an existing Pro btsnoop capture using read-back HID report handles."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snoop', type=Path, required=True)
    parser.add_argument('--hid-info', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--from-epoch', type=float)
    parser.add_argument('--to-epoch', type=float)
    parser.add_argument('--historical-hid-info', action='store_true',
                        help='The supplied handle/CCCD readback predates the selected trial')
    args = parser.parse_args()
    if (args.from_epoch is None) != (args.to_epoch is None):
        parser.error('Both time-window endpoints are required')
    if args.from_epoch is not None and args.from_epoch > args.to_epoch:
        parser.error('Time window is reversed')
    data = args.snoop.read_bytes()
    assert data[:16] == b'btsnoop\0' + struct.pack('>II', 1, 1002), 'Expected H4 btsnoop'
    info = args.hid_info.read_text(encoding='utf-8-sig')
    assert 'hex=01220081500100' in info and 'complete=true' in info, 'Successful Pro readback required'
    references, cccds = {}, {}
    for kind, instance, status, value in re.findall(
            r'READ descriptor=0000(290[28])-\S+ characteristic_instance=(\d+) status=(\d+) hex=([0-9a-f]+)', info):
        assert status == '0'
        if kind == '2908':
            raw = bytes.fromhex(value)
            assert len(raw) == 2 and raw[1] == 1, 'Input report reference required'
            references[int(instance)] = raw[0]
        else:
            cccds[int(instance)] = value
    assert 5 in references.values(), 'Pressure report reference missing'
    pressure_handle = next(handle for handle, report in references.items() if report == 5)
    assert cccds[pressure_handle] == '0100', 'Pressure notifications not enabled'
    position, packets, shortened = 16, 0, 0
    drops, links = set(), {}
    notifications, reports = Counter(), Counter()
    first, last, pen_address = None, None, '28:ce:15:31:70:0e'
    matched_link = False
    fragmented = 0
    packets_in_window, pen_att_in_window = 0, 0
    while position < len(data):
        assert position + 24 <= len(data), 'Truncated record header'
        original, included, flags, dropped, timestamp = struct.unpack_from('>IIIIQ', data, position)
        position += 24
        assert position + included <= len(data), 'Truncated packet'
        packet = data[position:position + included]
        position += included
        packets += 1
        shortened += original != included
        drops.add(dropped)
        first = timestamp if first is None else first
        last = timestamp
        epoch = (timestamp - 0x00dcddb30f2f8000) / 1e6
        in_window = args.from_epoch is None or args.from_epoch <= epoch <= args.to_epoch
        packets_in_window += in_window
        if len(packet) >= 15 and packet[:2] == bytes((4, 0x3e)) and packet[3] in (1, 0x0a) and packet[4] == 0:
            handle = struct.unpack_from('<H', packet, 5)[0]
            address = ':'.join(f'{b:02x}' for b in packet[9:15][::-1])
            links[handle] = address
            matched_link |= address == pen_address
        if len(packet) < 9 or packet[0] != 2:
            continue
        raw_handle, acl_length, length, cid = struct.unpack_from('<HHHH', packet, 1)
        handle = raw_handle & 0xfff
        if links.get(handle) != pen_address:
            continue
        if (raw_handle >> 12) & 3 == 1:
            fragmented += 1
            continue
        if cid != 4 or not (flags & 1):
            continue
        payload = packet[9:]
        assert acl_length == len(packet) - 5 and length == len(payload), 'Incomplete ATT packet'
        if not in_window:
            continue
        pen_att_in_window += 1
        if len(payload) >= 3 and payload[0] in (0x1b, 0x1d):
            attribute = struct.unpack_from('<H', payload, 1)[0]
            notifications[f'0x{attribute:04x}'] += 1
            if attribute in references:
                reports[str(references[attribute])] += 1
    assert matched_link, 'No captured connection for the exact Pro'
    assert shortened == 0 and drops == {0} and fragmented == 0, 'Incomplete trace; do not infer absence'
    def utc(timestamp):
        return datetime.fromtimestamp((timestamp - 0x00dcddb30f2f8000) / 1e6, timezone.utc).isoformat()
    report = dict(
        date_utc=datetime.now(timezone.utc).isoformat(), serial='ca10ede3', pen_address=pen_address,
        capture_start_utc=utc(first), capture_end_utc=utc(last), packets=packets,
        shortened_packets=shortened, recorded_drops=sorted(drops), fragmented_pen_acl_packets=fragmented,
        exact_pen_connection_observed=matched_link, protocol_mode='report' if 'instance=30 status=0 hex=01' in info else 'unverified',
        input_report_handles={str(report): f'0x{handle:04x}' for handle, report in references.items()},
        notification_cccd=cccds, notifications_by_attribute=dict(notifications),
        hid_notifications_by_report_id=dict(reports), pressure_notifications=reports['5'],
        pressure_notification_enabled_at_readback=True,
        limitation='CCCD readback was after the physical trial; this is captured transport evidence, not a writing repair or a diagnosis of the pen hardware.',
        files_sha256={str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (args.snoop, args.hid_info)},
        writing_fixed=False, controller_writes=0, passed=True)
    if args.from_epoch is not None:
        report.update(
            window_from_epoch=args.from_epoch, window_to_epoch=args.to_epoch,
            packets_in_window=packets_in_window, pen_att_packets_in_window=pen_att_in_window,
            capture_covers_window=(first - 0x00dcddb30f2f8000) / 1e6 <= args.from_epoch
                and (last - 0x00dcddb30f2f8000) / 1e6 >= args.to_epoch)
    if args.historical_hid_info:
        report.update(
            hid_metadata_current=False, protocol_mode='unverified_current',
            protocol_mode_at_historical_readback=report['protocol_mode'],
            pressure_notification_enabled_during_window=None,
            limitation='Handle mapping and CCCD values use a historical readback; '
                       'current CCCD reads were rejected. Missing captured notifications '
                       'do not establish the physical-trial subscription state.')
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('packets', 'hid_notifications_by_report_id', 'pressure_notifications', 'passed')}))


if __name__ == '__main__':
    main()
