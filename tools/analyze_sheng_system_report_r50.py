#!/usr/bin/env python3
"""Classify physical evdev cadence after standard setting/HAL transitions."""
import argparse
import json
from pathlib import Path
from analyze_sheng_touch_rate import analyze

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('events', type=Path)
    parser.add_argument('phases', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    phases = json.loads(args.phases.read_text(encoding='utf-8-sig'))
    assert phases['passed'] and not phases['direct_thp_setter_used']
    assert phases['setting'] == 'high_touch_polling_rate_enable'
    assert phases['initial']['desired'] == 0 and phases['final_requested'] == 1
    commands = phases['commands']
    assert [x['desired'] for x in commands] == [1, 0, 1]
    names = ['baseline', 'high', 'disabled', 'high_final']
    starts = [phases['initial']['after']+.1] + [x['after']+.1 for x in commands]
    ends = [x['before']-.1 for x in commands] + [None]
    windows = {name: analyze(args.events, start=start, end=end)
               for name, start, end in zip(names, starts, ends)}
    sufficient = all(x['sufficient'] for x in windows.values())
    expected = sufficient and all(
        270 <= windows[name]['median_report_hz'] <= 305 if 'high' in name else
        135 <= windows[name]['median_report_hz'] <= 155 for name in names)
    result = dict(windows=windows, sufficient=sufficient, expected_cadence_passed=expected,
                  setting=phases['setting'], final_requested=1,
                  measurement='Delivered report cadence including OEM interpolation; physical scan rate unproven')
    output = json.dumps(result, indent=2)+'\n'
    args.output.write_text(output)
    print(output, end='')
    raise SystemExit(0 if expected else 1)

if __name__ == '__main__':
    main()
