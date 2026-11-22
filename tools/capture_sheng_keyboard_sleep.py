#!/usr/bin/env python3
"""Capture an existing keyboard sleep incident without changing display or power."""
import argparse
import datetime
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', type=Path, required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=20, choices=range(5, 46))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    base = [str(args.adb), '-s', args.serial, 'shell']

    def capture(name, command):
        result = subprocess.run(base + [command], capture_output=True, timeout=60)
        (args.output / name).write_bytes(result.stdout + result.stderr)
        return result.returncode

    state = '''date; cat /proc/uptime; cat /proc/sys/kernel/random/boot_id;
uname -a; id; cat /proc/modules; dumpsys power;
cat /sys/class/misc/nanodev0/connection;
cat /sys/class/misc/nanodev0/firmware_generation;
cat /proc/interrupts; cat /sys/kernel/debug/wakeup_sources;
for p in /sys/bus/i2c/devices/5-004c/of_node/nanosic,*gpio*; do
  echo "$p"; od -An -tx1 "$p";
done; dumpsys display | grep mScreenState'''
    codes = {}
    codes['before'] = capture('before.txt', state)
    codes['dmesg_before'] = capture('dmesg-before.txt', 'dmesg')
    # An independent trace instance leaves existing tracing sessions untouched.
    instance = 'sheng_kb_sleep_' + datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    trace = f'''set -eu
t=/sys/kernel/tracing/instances/{instance}
mkdir "$t"
cleanup() {{
  echo 0 > "$t/tracing_on"
  echo 0 > "$t/events/gpio/gpio_value/enable"
  rmdir "$t"
}}
trap cleanup EXIT HUP INT TERM
echo 128 > "$t/buffer_size_kb"
echo 1 > "$t/events/gpio/gpio_value/enable"
echo 1 > "$t/tracing_on"
sleep {args.seconds}
echo 0 > "$t/tracing_on"
cat "$t/trace"
'''
    codes['gpio_trace'] = capture('gpio-trace.txt', trace)
    codes['after'] = capture('after.txt', state)
    codes['dmesg_after'] = capture('dmesg-after.txt', 'dmesg')
    codes['app_log'] = capture('app-log.txt',
        'logcat -d -s ShengKeyboard:I ShengKeyboardPresence:I -t 200')
    (args.output / 'capture.json').write_text(json.dumps({
        'created': datetime.datetime.now().astimezone().isoformat(),
        'serial': args.serial, 'seconds': args.seconds, 'returncodes': codes,
        'display_or_power_controls_changed': False,
        'trace_instance': instance, 'trace_instance_cleanup': 'EXIT trap',
        'status': 'diagnostic_evidence_only',
    }, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'returncodes': codes}))


if __name__ == '__main__':
    main()
