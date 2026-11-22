#!/usr/bin/env python3
"""Analyze verified THP socket transitions separately from physical scan rate."""
import argparse
import json
import re
from pathlib import Path
from analyze_sheng_touch_rate import analyze

p = argparse.ArgumentParser()
p.add_argument('input', type=Path)
p.add_argument('--output', type=Path)
args = p.parse_args()
source = args.input.read_text()
report_only = 'mode=202 comparison' in source
if report_only:
    pattern = r'TRANSITION desired=(\d) before=(\d+\.\d+) after=(\d+\.\d+) ack=(\d) daemon_game=(\d)'
    transitions = [dict(desired=int(a), before=float(b), after=float(c), ack=int(d), daemon_game=int(e))
                   for a, b, c, d, e in re.findall(pattern, source)]
    assert all(x['ack'] == 1 and x['daemon_game'] == 0 for x in transitions)
else:
    pattern = r'TRANSITION desired=(\d) before=(\d+\.\d+) after=(\d+\.\d+) readback=(\d)'
    transitions = [dict(desired=int(a), before=float(b), after=float(c), readback=int(d))
                   for a, b, c, d in re.findall(pattern, source)]
    assert all(x['desired'] == x['readback'] for x in transitions)
assert len(transitions) == 2 and [x['desired'] for x in transitions] == [1, 0]
finish = re.search(r'FINISHED success=(\d) restored=(\d) syn_dropped=(\d+)', source)
assert finish and finish[2] == '1' and finish[3] == '0'
enable, disable = transitions
result = dict(transitions=transitions, mode=202 if report_only else 0,
              native_frame_goal_complete=finish[1] == '1',
              restored=True, baseline=analyze(args.input, end=enable['before']-.1),
              daemon_game=analyze(args.input, start=enable['after']+.1, end=disable['before']-.1),
              baseline_restored=analyze(args.input, start=disable['after']+.1),
              scope='THP delivered cadence. Extra interpolated reports are not evidence of higher physical IC sampling.')
result['sufficient'] = all(result[key]['sufficient']
                           for key in ['baseline', 'daemon_game', 'baseline_restored'])
firmware = re.findall(r'FIRMWARE phase=(\d) time=(\d+\.\d+) hand_scan_rate: (\d+)', source)
if firmware:
    result['firmware_hand_scan_readback'] = [dict(phase=int(a), time=float(b), hz=int(c))
                                           for a, b, c in firmware]
    assert [x['phase'] for x in result['firmware_hand_scan_readback']] == [0, 1, 2]
output = json.dumps(result, indent=2)+'\n'
if args.output:
    assert not args.output.exists()
    args.output.write_text(output)
print(output, end='')
raise SystemExit(0 if result['sufficient'] else 1)
