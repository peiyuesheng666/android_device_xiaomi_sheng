#!/usr/bin/env python3
"""Install the qualified DP/USB candidate against its exact tablet baseline."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--name', default='dp-usb-kernel-20261118')
parser.add_argument('--serial', default='192.168.1.139:5555')
args = parser.parse_args()
def report_path(kind):
    name = 'dp-usb-kernel-' + kind + '-20261118' if args.name == 'dp-usb-kernel-20261118' else args.name + '-' + kind
    return workspace / 'reports' / (name + '.json')
workspace = Path(__file__).resolve().parents[4]
adb = [str(workspace / 'tools/platform-tools/adb.exe'), '-s', args.serial]
artifact = workspace / 'artifacts' / args.name
receipt_path = report_path('install')
assert not receipt_path.exists(), 'Preserve the previous installation receipt'
package = json.loads(report_path('package').read_text())
assert package['passed']
baseline = package['baseline']
state = dict(device=baseline['device'], slot=baseline['slot'], address=args.serial,
             events=[], complete=False)

def event(name, **data):
    state['events'].append(dict(event=name, **data))
    receipt_path.write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps(state['events'][-1]), flush=True)

def call(*args, timeout=60):
    return subprocess.check_output(adb + list(map(str, args)), timeout=timeout).decode().strip()

def shell(command, timeout=60):
    return call('shell', command, timeout=timeout)

def remote_sha(path):
    return shell('sha256sum ' + path).split()[0]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

remote = '/data/local/tmp/sheng-' + args.name
partition = baseline['remote']
try:
    assert shell('getprop ro.serialno') == baseline['device'] == 'ca10ede3'
    assert shell('getprop ro.product.device') == 'sheng'
    assert shell('getprop ro.boot.slot_suffix') == baseline['slot'] == '_b'
    assert shell('id -u') == '0'
    assert shell('getprop sys.boot_completed') == '1'
    assert int(shell('cat /sys/class/power_supply/battery/capacity')) >= 30
    assert remote_sha(partition) == baseline['sha256']
    assert shell('blockdev --getsize64 ' + partition) == str(baseline['bytes'])
    # Verification must already be disabled; never change the verified boot policy.
    vbmeta = subprocess.check_output(adb + ['exec-out', 'cat', '/dev/block/by-name/vbmeta_b'], timeout=30)
    assert vbmeta[:4] == b'AVB0' and int.from_bytes(vbmeta[120:124], 'big') & 2
    state['boot_id_before'] = shell('cat /proc/sys/kernel/random/boot_id')
    state['persist_adb_tcp_port_before'] = shell('getprop persist.adb.tcp.port')
    state['boot_sha256_before'] = remote_sha('/dev/block/by-name/boot_b')
    state['init_boot_sha256_before'] = remote_sha('/dev/block/by-name/init_boot_b')
    image = workspace / package['candidate_path']
    rollback = artifact / 'vendor_boot_b.before.img'
    assert sha(image) == package['candidate_sha256']
    assert sha(rollback) == baseline['sha256']
    for row in package['changed']:
        name = Path(row['path']).stem
        assert remote_sha('/vendor/lib/modules/' + name + '.ko') == row['before']
        assert sha(artifact / (name + '.signed.ko')) == row['after']
        assert sha(artifact / (name + '.before.ko')) == row['before']
    event('identity_baseline_abi_package_and_backup_verified')
    shell('mkdir -p ' + remote)
    call('push', image, remote + '/vendor_boot.img', timeout=180)
    call('push', rollback, remote + '/vendor_boot.before.img', timeout=180)
    assert remote_sha(remote + '/vendor_boot.img') == package['candidate_sha256']
    assert remote_sha(remote + '/vendor_boot.before.img') == baseline['sha256']
    for row in package['changed']:
        name = Path(row['path']).stem
        call('push', artifact / (name + '.signed.ko'), remote + '/' + name + '.ko')
        assert remote_sha(remote + '/' + name + '.ko') == row['after']
        call('push', artifact / (name + '.before.ko'), remote + '/' + name + '.before.ko')
        assert remote_sha(remote + '/' + name + '.before.ko') == row['before']
    event('candidate_and_rollback_uploaded_and_verified')
    # A temporarily persistent port keeps the already authorized wireless transport
    # available across this test reboot; restore its original value after boot.
    shell('setprop persist.adb.tcp.port 5555')
    assert shell('getprop persist.adb.tcp.port') == '5555'
    remount = subprocess.run(adb + ['remount'], capture_output=True, timeout=60)
    event('remount_attempt', returncode=remount.returncode,
          output=(remount.stdout + remount.stderr).decode(errors='replace'))
    # Probe only the target module directory before writing either boot payload.
    shell('touch /vendor/lib/modules/.sheng-dp-usb-write-test && rm /vendor/lib/modules/.sheng-dp-usb-write-test')
    replaced = []
    partition_written = False
    try:
        for row in package['changed']:
            name = Path(row['path']).stem
            target = '/vendor/lib/modules/' + name + '.ko'
            shell('cp ' + remote + '/' + name + '.ko ' + target + '.new && chown 0:0 ' + target + '.new && chmod 0644 ' + target + '.new && restorecon ' + target + '.new && mv -f ' + target + '.new ' + target + ' && restorecon ' + target)
            replaced.append(name)
            assert remote_sha(target) == row['after']
        event('vendor_module_copies_verified')
        partition_written = True
        shell('dd if=' + remote + '/vendor_boot.img of=' + partition + ' bs=4M conv=fsync && sync', timeout=120)
        assert remote_sha(partition) == package['candidate_sha256']
        assert remote_sha('/dev/block/by-name/boot_b') == state['boot_sha256_before']
        assert remote_sha('/dev/block/by-name/init_boot_b') == state['init_boot_sha256_before']
        event('vendor_boot_full_partition_readback_verified')
    except BaseException:
        if partition_written:
            shell('dd if=' + remote + '/vendor_boot.before.img of=' + partition + ' bs=4M conv=fsync && sync', timeout=120)
            assert remote_sha(partition) == baseline['sha256']
        for name in replaced:
            target = '/vendor/lib/modules/' + name + '.ko'
            shell('cp ' + remote + '/' + name + '.before.ko ' + target + ' && chown 0:0 ' + target + ' && chmod 0644 ' + target + ' && restorecon ' + target)
        shell('setprop persist.adb.tcp.port "' + state['persist_adb_tcp_port_before'] + '"')
        event('pre_reboot_failure_restored_baseline')
        raise
    state['complete'] = True
    state['reboot_pending'] = True
    event('installation_verified_reboot_pending')
except BaseException as error:
    event('failed', error=str(error))
    raise
