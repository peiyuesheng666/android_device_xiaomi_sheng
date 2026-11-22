#!/usr/bin/env python3
"""Extract measured pump input and firmware targets from recorded charger logs.

All values retain their source line. A PD contract is a requested capability,
not a measured input; the USB supply current is not substituted for pump input.
"""
import argparse
import json
from pathlib import Path
import re


def analyze(text):
    result = dict(pump_samples=[], tune_samples=[], contracts=[], step_config=[])
    seen = set()
    for number, line in enumerate(text.splitlines(), 1):
        # IPC log reads may repeat a retained firmware message.
        if line in seen:
            continue
        seen.add(line)
        base = dict(line=number)
        m = re.search(r'vbus_bq_mv = (\d+), ibus_bq_ma = (\d+), ibus_slave_bq_ma = (\d+), ibus_total_ma = (\d+)', line)
        if m:
            mv, main, slave, total = map(int, m.groups())
            result['pump_samples'].append(dict(base, bus_mv=mv, main_ma=main,
                slave_ma=slave, total_with_switcher_ma=total,
                estimated_pump_input_w=round(mv*(main+slave)/1e6, 3)))
        m = re.search(r'ibat: (\d+)/(\d+)/(\d+), ibus: (\d+)/(\d+)/(\d+), vbat: (\d+)/(\d+), steps: (-?\d+)', line)
        if m:
            values = map(int, m.groups())
            keys = ['battery_actual_ma', 'battery_target_ma', 'battery_deficit_ma',
                    'bus_actual_ma', 'bus_target_ma', 'bus_deficit_ma',
                    'battery_mv', 'battery_limit_mv', 'steps']
            result['tune_samples'].append(dict(base, **dict(zip(keys, values))))
        m = re.search(r'DPM: PD Contract Update.*voltage_mv=(\d+) mV, current_ma=(\d+) mA, bPPS=(\d+)', line)
        if m:
            mv, ma, pps = map(int, m.groups())
            result['contracts'].append(dict(base, requested_mv=mv, requested_ma=ma, pps=bool(pps)))
        m = re.search(r'step (\d+) StepParam (\d+) fcc_now (\d+)', line)
        if m:
            step, param, fcc = map(int, m.groups())
            result['step_config'].append(dict(base, step=step, voltage_parameter_mv=param, fcc_ma=fcc))
    result['notes'] = [
        'Targets and contracts are not measured power or proof of a software limit.',
        'Pump input watts are an estimate from one firmware line; switcher current is excluded.',
        'Missing log records do not prove an event did not occur.',
    ]
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('log', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    raw = a.log.read_bytes()
    encoding = 'utf-16' if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8-sig'
    report = analyze(raw.decode(encoding))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key:len(report[key]) for key in ('pump_samples','tune_samples','contracts','step_config')}))
