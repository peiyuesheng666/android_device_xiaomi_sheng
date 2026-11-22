#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Temporarily collect charger firmware diagnostics; restore logging settings."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--serial', required=True)
p.add_argument('--expected-serial', required=True)
p.add_argument('--samples', type=int, default=4)
a = p.parse_args()
assert re.fullmatch('[a-zA-Z0-9._-]+', a.expected_serial)
assert 1 <= a.samples <= 12
w = Path(__file__).resolve().parents[4]
adb = [str(w/'tools/platform-tools/adb.exe'), '-s', a.serial]
assert subprocess.check_output(adb+['shell','getprop ro.serialno'], timeout=10).decode().strip() == a.expected_serial
out = w/'reports'/('charging-firmware-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
out.mkdir(parents=True)
command = r'''
set -eu
test "$(getprop ro.serialno)" = EXPECTED
d=/sys/kernel/debug/charger_ulog
en=$(cat "$d/enable"); category=$(cat "$d/category"); level=$(cat "$d/level")
echo "ORIGINAL: enable=$en category=$category level=$level"
test "$en" = 0
restore() {
    echo 0 > "$d/enable"
    echo "$category" > "$d/category"
    echo "$level" > "$d/level"
    echo RESTORED
    cat "$d/enable" "$d/category" "$d/level"
}
trap restore EXIT
trap 'exit 130' HUP INT TERM
echo 4294967295 > "$d/category"
echo 3 > "$d/level"
echo 1 > "$d/enable"
for i in SAMPLE_LIST; do
    sleep 5
    echo "SAMPLE:$i"; date; cat /proc/uptime
    timeout 2 cat /sys/kernel/debug/ipc_logging/charger_ulog/log || true
    for s in battery usb; do
        echo "SUPPLY:$s"
        cat "/sys/class/power_supply/$s/uevent"
    done
    for n in real_type pd_verifed verify_process adapter_id adapter_svid apdo_max power_max current_state quick_charge_type fastchg_mode authentic slave_authentic bap_match input_suspend restrict_chg restrict_cur screen_cctog blank_status connector_temp thermal_board_temp average_temp fg1_temp fg2_temp bq2597x_bus_voltage bq2597x_bus_current bq2597x_slave_bus_current bq2597x_battery_voltage bq2597x_chip_ok bq2597x_slave_chip_ok; do
        echo "NODE:$n"
        node="/sys/class/qcom-battery/$n"
        if [ -r "$node" ]; then cat "$node"; else echo unavailable; fi
    done
done
'''.replace('EXPECTED', a.expected_serial).replace('SAMPLE_LIST', ' '.join(map(str, range(1, a.samples + 1))))
(out/'command.sh').write_text(command, encoding='utf-8')
try:
    print('CAPTURING: ' + str(out), flush=True)
    r = subprocess.run(adb+['shell', command], capture_output=True, timeout=7 * a.samples + 25)
    (out/'firmware.log').write_bytes(r.stdout)
    (out/'errors.txt').write_bytes(r.stderr)
    assert r.returncode == 0, r.stderr.decode(errors='replace')
finally:
    # Independent readback; device-side EXIT trap restores even on host failure.
    check = subprocess.run(adb+['shell','cat /sys/kernel/debug/charger_ulog/enable /sys/kernel/debug/charger_ulog/category /sys/kernel/debug/charger_ulog/level'], capture_output=True, timeout=10)
    (out/'restore.json').write_text(json.dumps(dict(rc=check.returncode, stdout=check.stdout.decode(errors='replace'),stderr=check.stderr.decode(errors='replace')), indent=2), encoding='utf-8')
print(out, flush=True)
