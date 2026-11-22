#!/usr/bin/env python3
"""Wait for the test reboot, restore ADB policy, and collect kernel evidence."""
import argparse
import json
from pathlib import Path
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--name', default='dp-usb-kernel-20261118')
parser.add_argument('--serial', help='ADB transport after reboot, if it changed')
args = parser.parse_args()
def report_path(kind):
    name = 'dp-usb-kernel-' + kind + '-20261118' if args.name == 'dp-usb-kernel-20261118' else args.name + '-' + kind
    return workspace / 'reports' / (name + '.json')
workspace = Path(__file__).resolve().parents[4]
adb = str(workspace / 'tools/platform-tools/adb.exe')
receipt = report_path('install')
state = json.loads(receipt.read_text())
address = args.serial or state.get('address', '192.168.1.139:5555')
report_dir = workspace / 'reports' / ('dp-usb-kernel-live-20261118' if args.name == 'dp-usb-kernel-20261118' else args.name + '-live')
report_dir.mkdir(exist_ok=True)

def shell(command, timeout=10):
    return subprocess.check_output([adb, '-s', address, 'shell', command],
                                   timeout=timeout, stderr=subprocess.DEVNULL).decode().strip()

start = time.monotonic()
while time.monotonic() - start < 240:
    try:
        subprocess.run([adb, 'connect', address], capture_output=True, timeout=5)
        if shell('getprop sys.boot_completed') == '1':
            assert shell('getprop ro.serialno') == 'ca10ede3'
            assert shell('getprop ro.boot.slot_suffix') == '_b'
            boot = shell('cat /proc/sys/kernel/random/boot_id')
            if boot != state['boot_id_before']:
                break
    except (subprocess.SubprocessError, OSError):
        pass
    time.sleep(3)
else:
    raise TimeoutError('New Android boot not observed within 240 seconds')
if shell('id -u') != '0':
    subprocess.run([adb, '-s', address, 'root'], check=True, timeout=30)
    subprocess.run([adb, '-s', address, 'wait-for-device'], check=True, timeout=30)
assert shell('id -u') == '0'
shell('setprop persist.adb.tcp.port "' + state['persist_adb_tcp_port_before'] + '"')
assert shell('getprop persist.adb.tcp.port') == state['persist_adb_tcp_port_before']
package = json.loads(report_path('package').read_text())
assert shell('sha256sum /dev/block/by-name/vendor_boot_b').split()[0] == package['candidate_sha256']
for partition in ('boot', 'init_boot'):
    assert shell('sha256sum /dev/block/by-name/' + partition + '_b').split()[0] == state[partition + '_sha256_before']
for row in package['changed']:
    assert shell('sha256sum /vendor/' + row['path']).split()[0] == row['after']
dmesg = shell('dmesg', timeout=30)
(report_dir / 'dmesg.txt').write_text(dmesg + '\n')
snapshot = shell('ls -l /sys/class/drm; cat /proc/modules; dumpsys display; dumpsys usb', timeout=30)
(report_dir / 'display-usb.txt').write_text(snapshot + '\n')
result = dict(device='ca10ede3', boot_id=boot, boot_completed=True,
              vendor_boot_sha256=package['candidate_sha256'], module_hashes_verified=True,
              adb_persistent_port_restored=True,
              legacy_pll_registered='sheng legacy DP PLL 4nm-v1.1 clocks registered' in dmesg,
              previous_ssphy_clock_warning='devm_clk_hw_get_clk' in dmesg,
              dp_lines=[line for line in dmesg.splitlines() if any(term in line.lower() for term in
                        ('dp_pll', 'dp_init_sub', 'dp_display', 'dp_aux', 'dp_hpd', 'ps5169', 'ssphy', 'qmp'))])
(report_dir / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
state.update(reboot_pending=False, boot_id_after=boot, boot_verified=True,
             adb_persistent_port_restored=True, runtime_report=str(report_dir.relative_to(workspace)))
receipt.write_text(json.dumps(state, indent=2) + '\n')
print(json.dumps(result, indent=2), flush=True)
