#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read-only charger, authentication and limiter snapshot over existing ADB."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import time

NODES = '''real_type usb_real_type typec_mode pd_verifed verify_process adapter_id
adapter_svid apdo_max power_max pdo2 current_state quick_charge_type fastchg_mode
fg1_fastcharge fg2_fastcharge fg1_current_max fg2_current_max fg1_vol fg2_vol
fg1_ibatt fg2_ibatt fg1_temp fg2_temp authentic slave_authentic bap_match
charging_suspend_battery input_suspend restrict_chg restrict_cur screen_cctog
blank_status night_charging smart_batt smart_chg connector_temp thermal_board_temp
average_temp constant_power pps_ptf cp_ovp_mode bq2597x_bus_voltage
bq2597x_bus_current bq2597x_slave_bus_current bq2597x_battery_voltage
bq2597x_chip_ok bq2597x_slave_chip_ok'''.split()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--serial', required=True)
    p.add_argument('--expected-serial', required=True)
    p.add_argument('--samples', type=int, default=3)
    p.add_argument('--interval', type=float, default=5)
    p.add_argument('--label', default='baseline')
    args = p.parse_args()
    assert 1 <= args.samples <= 60 and 0 <= args.interval <= 30
    assert re.fullmatch('[a-zA-Z0-9-]+', args.label)
    workspace = Path(__file__).resolve().parents[4]
    adb = [str(workspace/'tools/platform-tools/adb.exe'), '-s', args.serial]
    out = workspace/'reports'/('charging-' + args.label + '-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    def read(cmd):
        try:
            r = subprocess.run(adb+['shell', cmd], capture_output=True, timeout=25)
            return dict(rc=r.returncode, stdout=r.stdout.decode(errors='replace'), stderr=r.stderr.decode(errors='replace'))
        except subprocess.TimeoutExpired:
            return dict(timeout=True)
    def verify():
        assert read('getprop ro.serialno').get('stdout', '').strip() == args.expected_serial, 'Device identity mismatch'
    verify(); out.mkdir(parents=True)
    state = dict(read_only=True, transport=args.serial, serial=args.expected_serial,
                 identity=read('id; uname -a; cat /proc/sys/kernel/random/boot_id; getprop ro.build.fingerprint; getprop init.svc.batterysecret; getprop init.svc.mi_thermald; getprop init.svc.micharge'), samples=[])
    cmd = ('date; cat /proc/uptime; '
           'for s in battery usb; do echo SUPPLY:$s; cat /sys/class/power_supply/$s/uevent; done; '
           'for n in ' + ' '.join(NODES) + '; do printf "NODE:%s=" "$n"; cat /sys/class/qcom-battery/"$n"; printf "\\n"; done; '
           'for d in /sys/class/thermal/cooling_device*; do echo COOLING:$d; cat "$d/type" "$d/cur_state" "$d/max_state"; done')
    for i in range(args.samples):
        verify()
        row = dict(time=datetime.now().astimezone().isoformat(), data=read(cmd))
        state['samples'].append(row)
        (out/'state.json').write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        print(row['data'].get('stdout', ''), flush=True)
        if i + 1 < args.samples: time.sleep(args.interval)
    for name, command in {
        'dmesg': 'dmesg', 'thermal': 'dumpsys thermalservice; dumpsys battery',
        'processes': 'ps -AZ; getprop',
        'logcat': 'logcat -b all -d -v threadtime -t 8000',
        'thermal-files': 'ls -l /vendor/etc/*thermal* /odm/etc/*thermal* /data/vendor/thermal; cat /sys/class/thermal/thermal_message/temp_state; cat /sys/class/thermal/thermal_message/sconfig; cat /sys/class/thermal/thermal_message/board_sensor_temp; cat /sys/class/thermal/thermal_message/board_sensor_temp_comp; cat /sys/class/thermal/thermal_message/board_sensor_second_temp',
    }.items():
        verify()
        result = read(command)
        (out/(name+'.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('OUTPUT: ' + str(out), flush=True)

if __name__ == '__main__':
    main()
