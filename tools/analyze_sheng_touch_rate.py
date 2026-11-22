#!/usr/bin/env python3
"""Measure delivered evdev reports during single-finger strokes, not IC scan latency."""
import argparse
import json
from pathlib import Path
import re
import statistics


def analyze(path, start=None, end=None):
    pattern = re.compile(r'^\[\s*(\d+\.\d+)\]\s+(?:/dev/input/event\d+:\s+)?'
                         r'(EV_\w+)\s+(\w+)\s+(\w+)')
    slots = {}
    slot = 0
    previous = None
    intervals = []
    reports = active_reports = dropped = rejected = 0
    for line in path.read_text().splitlines():
        match = pattern.match(line)
        if not match:
            continue
        timestamp, kind, code, value = match.groups()
        if kind == 'EV_ABS' and code == 'ABS_MT_SLOT':
            slot = int(value, 16)
        elif kind == 'EV_ABS' and code == 'ABS_MT_TRACKING_ID':
            if value.lower() == 'ffffffff':
                slots.pop(slot, None)
            else:
                slots[slot] = int(value, 16)
        elif kind == 'EV_SYN' and code == 'SYN_DROPPED':
            slots.clear()
            previous = None
            dropped += 1
        elif kind == 'EV_SYN' and code == 'SYN_REPORT':
            now = float(timestamp)
            if (start is not None and now < start) or (end is not None and now > end):
                previous = None
                continue
            reports += 1
            if len(slots) != 1:
                previous = None
                continue
            active_reports += 1
            contact = next(iter(slots.items()))
            if previous is not None and previous[0] == contact:
                delta = (now - previous[1]) * 1000
                # Exclude pauses and malformed/duplicate timestamps explicitly.
                if 0.1 <= delta <= 50:
                    intervals.append(delta)
                else:
                    rejected += 1
            previous = contact, now
    result = dict(input=str(path.resolve()), reports=reports,
                  single_finger_reports=active_reports, usable_intervals=len(intervals),
                  excluded_pause_or_invalid_intervals=rejected, syn_dropped=dropped,
                  sufficient=len(intervals) >= 500 and dropped == 0,
                  measurement='Delivered evdev report cadence; firmware scan rate and end-to-end latency unproven')
    if start is not None or end is not None:
        result['window_seconds'] = dict(start=start, end=end)
    if intervals:
        ordered = sorted(intervals)
        result.update(median_interval_ms=statistics.median(ordered),
                      median_report_hz=1000 / statistics.median(ordered),
                      p10_interval_ms=ordered[int((len(ordered)-1)*.1)],
                      p90_interval_ms=ordered[int((len(ordered)-1)*.9)],
                      fraction_intervals_under_5ms=sum(x < 5 for x in ordered)/len(ordered))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--phases', type=Path, help='Verified stock game-mode transition timestamps')
    args = parser.parse_args()
    if args.phases:
        phases = json.loads(args.phases.read_text(encoding='utf-8-sig'))
        assert phases['passed'] and phases['gameRestored']
        enable, disable = phases['commands']
        assert enable['desired'] == 1 and disable['desired'] == 0
        result = dict(baseline=analyze(args.input, end=enable['before']-.1),
                      game=analyze(args.input, start=enable['after']+.1, end=disable['before']-.1),
                      restored=analyze(args.input, start=disable['after']+.1))
        sufficient = result['baseline']['sufficient'] and result['game']['sufficient']
    else:
        result = analyze(args.input)
        sufficient = result['sufficient']
    text = json.dumps(result, indent=2) + '\n'
    if args.output:
        assert not args.output.exists(), 'Do not overwrite prior measurements'
        args.output.write_text(text)
    print(text, end='')
    raise SystemExit(0 if sufficient else 1)


if __name__ == '__main__':
    main()
