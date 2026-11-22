#!/usr/bin/env python3
"""Summarize only real HID / THP / NVT observations from the bounded trial."""
import argparse
import json
from pathlib import Path
import re

p = argparse.ArgumentParser()
p.add_argument('trial', type=Path)
args = p.parse_args()
pressure = args.trial / 'pressure.txt'
mipp = args.trial / 'mipp.txt'
hid = []
acks = []
events = []
finish = None
for line in pressure.read_text(encoding='utf-8-sig').splitlines():
    report = re.fullmatch(r'HID time=([0-9.]+) report=([0-9a-f]{30})', line)
    if report:
        data = bytes.fromhex(report[2])
        if data[0] != 5:
            raise SystemExit('Unexpected accepted HID report ID')
        hid.append({'time': float(report[1]), 'pressure_le16': data[1] | data[2] << 8})
    ack = re.fullmatch(r'ACK panel=(\d+) op=(\d+) mode=(\d+) count=(\d+) data0=(-?\d+)', line)
    if ack:
        acks.append(tuple(map(int, ack.groups())))
    event = re.fullmatch(r'NVT endpoint=(\d+) time=([0-9.]+) type=(\d+) code=(\d+) value=(-?\d+)', line)
    if event:
        events.append({'endpoint': int(event[1]), 'time': float(event[2]),
                       'type': int(event[3]), 'code': int(event[4]), 'value': int(event[5])})
    if line.startswith('FINISHED '):
        finish = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', line)}
def limits(values):
    return {'count': len(values), 'min': min(values), 'max': max(values),
            'distinct': len(set(values))} if values else {'count': 0, 'distinct': 0}
summary = {
    'complete_log': finish is not None,
    'real_hid_reports': len(hid),
    'raw_pressure_values': limits([h['pressure_le16'] for h in hid]),
    'valid_thp_acks': sum(a[:4] == (0, 7, 1088, 0) for a in acks),
    'invalid_thp_acks': sum(a[:4] != (0, 7, 1088, 0) for a in acks),
    'nvt_events': len(events),
    'nvt_x': limits([e['value'] for e in events if e['type'] == 3 and e['code'] == 0]),
    'nvt_y': limits([e['value'] for e in events if e['type'] == 3 and e['code'] == 1]),
    'nvt_pressure': limits([e['value'] for e in events if e['type'] == 3 and e['code'] == 24]),
    'syn_dropped': sum(e['type'] == 0 and e['code'] == 3 for e in events),
    'native_finish': finish,
    'user_writing_acceptance': 'requires separate user confirmation',
}
if finish and (finish['reports'] != len(hid) or finish['nvt_events'] != len(events)):
    raise SystemExit('Native totals and parsed observations differ')
text = mipp.read_text(encoding='utf-8-sig')
gatt_pressure = [int(value) for value in re.findall(r'(?m)^PRESSURE_GATT_REPORT5 length=14 hex=[0-9a-f]{28} pressure_le16=(\d+)$', text)]
summary['gatt_pressure_values'] = limits(gatt_pressure)
summary['report5_subscription_status'] = [int(value) for value in re.findall(r'PRESSURE_REPORT5_SUBSCRIPTION status=(\d+)', text)]
summary['undock_observed'] = 'PHYSICAL UNDOCK' in text
summary['active_notifications'] = text.count('MIPP notification=53')
summary['screen_on_ack'] = 'MIPP notification=e100' in text
summary['post_init_timing_ack'] = 'POST_INIT_TIMING_ACK id=' in text
summary['assigned_ids'] = [int(value, 16) for value in re.findall(r'MIPP notification=8401([0-9a-f]{2})', text)]
summary['panel_requests'] = len(re.findall(r'(?m)^PANEL_REQUEST ', text))
summary['panel_frequency_acks'] = len(re.findall(r'(?m)^PANEL_FREQUENCY_APPLIED ', text))
summary['mipp_cleanup_succeeded'] = 'Restore ready=true disconnect=true' in text
cleanup=args.trial/'cleanup.txt'
retry_text=cleanup.read_text(encoding='utf-8-sig') if cleanup.exists() else ''
ready_restored = 'Restore ready=true' in text or 'pen_ioctl mode=37 value=0 result=0' in retry_text
disconnect_restored = bool(re.search(r'Restore ready=\w+ disconnect=true', text)) or 'pen_ioctl mode=20 value=8 result=0' in retry_text
summary['retry_cleanup_succeeded'] = ready_restored and disconnect_restored
summary['restore_succeeded'] = summary['mipp_cleanup_succeeded'] or summary['retry_cleanup_succeeded']
receipt_path = args.trial / 'trial-receipt.json'
if receipt_path.exists():
    receipt = json.loads(receipt_path.read_text(encoding='utf-8-sig'))
    # A receipt records whether this run owned a connection and handles per-action
    # retries; an early deferred cleanup stays in the original log as evidence.
    summary['cleanup_receipt_succeeded'] = receipt.get('cleanup_succeeded') is True
    summary['screen_timeout_restored'] = str(receipt.get('previous_timeout')) == str(receipt.get('restored_timeout'))
    if receipt.get('cleanup_succeeded') is False:
        summary['restore_succeeded'] = False
user_result_path = args.trial / 'user-pressure-result.json'
if user_result_path.exists():
    user_result = json.loads(user_result_path.read_text(encoding='utf-8-sig'))
    summary['user_writing_acceptance'] = user_result.get('writing_accepted') is True
    summary['user_line_width_response_acceptance'] = user_result.get('line_width_response_accepted') is True
    summary['user_feedback'] = user_result.get('user_feedback')
summary['real_variable_pressure_path_observed'] = (
    bool(hid) and summary['raw_pressure_values'].get('distinct', 0) > 2
    and summary['valid_thp_acks'] == len(hid) and summary['invalid_thp_acks'] == 0
    and summary['nvt_pressure'].get('distinct', 0) > 2)
out = args.trial / 'analysis.json'
out.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
print(json.dumps(summary, indent=2))
