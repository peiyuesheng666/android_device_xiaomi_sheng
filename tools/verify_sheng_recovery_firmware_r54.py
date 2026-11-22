#!/usr/bin/env python3
"""Read back the r54 Recovery and its automatic battery initialization.

This does not change partitions, SELinux state, firmware paths or DSP state.
It requires the recorded ca10ede3/A baseline and a boot of the r54 image.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

DEVICE = Path(__file__).resolve().parents[1]
WORKSPACE = DEVICE.parents[2]
REVIEW = WORKSPACE / 'reports/device/20261112-recovery-pen'


def hashes(text):
    return dict((name, digest) for digest, name in
                re.findall(r'^([0-9a-f]{64})\s+(\S+)\s*$', text, re.M))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', type=Path, required=True)
    parser.add_argument('--revision', type=int, choices=(54, 55, 56, 57, 58, 59), default=54)
    args = parser.parse_args()
    commands = []

    def read(command):
        result = subprocess.run([str(args.adb), '-s', 'ca10ede3', 'shell', command],
                                capture_output=True, text=True, timeout=30)
        commands.append({'command': command, 'returncode': result.returncode,
                         'stdout': result.stdout, 'stderr': result.stderr})
        (REVIEW / ('r%d-verification-commands.json' % args.revision)).write_text(
            json.dumps(commands, indent=2) + '\n')
        result.check_returncode()
        return result.stdout.strip()

    package_name = ('r%d-package.json' % args.revision) if args.revision >= 55 else 'recovery-package-receipt.json'
    packaged = json.loads((REVIEW / package_name).read_text())
    compiled = json.loads((REVIEW / 'policy-build-receipt.json').read_text())
    assert packaged['revision'] == args.revision and packaged['avb_verified']
    assert compiled['neverallows_enforced'] and compiled['permissive_domains_unchanged']
    assert compiled['recovery_only_type_label_and_permissions_verified']
    assert read('getprop ro.boot.serialno') == 'ca10ede3'
    assert read('getprop ro.boot.slot_suffix') == '_a'
    assert read('getenforce') == 'Enforcing'
    marker = {54: 'r54-firmware-path', 55: 'r55-menu-battery',
              56: 'r56-battery-events', 57: 'r57-parallel-modules',
              58: 'r58-late-oops-module', 59: 'r59-ordered-late-oops'}[args.revision]
    assert 'sheng_recovery_test='+marker in read('cat /proc/cmdline')
    assert read('cat /sys/module/firmware_class/parameters/path') == '/firmware/image'
    assert 'u:object_r:vendor_sysfs_sheng_firmware_path:s0' in read(
        'ls -lZ /sys/module/firmware_class/parameters/path')

    paths = ['/dev/block/by-name/' + name for name in
             ('recovery_a', 'recovery_b', 'boot_a', 'dtbo_a')]
    paths += ['/sepolicy', '/system/bin/sheng-recovery-hardware']
    if args.revision >= 55:
        paths.append('/system/lib64/librecovery_ui_ext.so')
    if args.revision >= 56:
        paths.append('/init.recovery.qcom.rc')
    if args.revision >= 58:
        paths += ['/system/etc/init/init.recovery.sheng-late-modules.rc',
                  '/system/bin/sheng-recovery-late-modules']
    actual = hashes(read('sha256sum ' + ' '.join(paths)))
    before = hashes((REVIEW / 'r54-preflash.txt').read_text(encoding='utf-8-sig'))
    assert actual[paths[0]] == packaged['sha256']
    for path in paths[1:4]:
        assert actual[path] == before[path], path
    assert actual['/sepolicy'] == compiled['candidate_policy_sha256']
    script_sha = packaged['startup_sources']['rootdir/recovery/hardware.sh'] if args.revision >= 56 else compiled['hardware_script_sha256']
    assert actual['/system/bin/sheng-recovery-hardware'] == script_sha
    for relative, digest in compiled['sources'].items():
        assert hashlib.sha256((DEVICE / relative).read_bytes()).hexdigest() == digest
    if args.revision >= 55:
        assert actual['/system/lib64/librecovery_ui_ext.so'] == packaged['ui_build']['sha256']
    if args.revision >= 56:
        for relative, digest in packaged['startup_sources'].items():
            assert hashlib.sha256((DEVICE / relative).read_bytes()).hexdigest() == digest
        assert actual['/init.recovery.qcom.rc'] == packaged['startup_sources']['rootdir/recovery/init.recovery.sheng.rc']
    if args.revision >= 58:
        for relative, installed in {
            'rootdir/recovery/init.recovery.sheng-late-modules.rc': '/system/etc/init/init.recovery.sheng-late-modules.rc',
            'rootdir/recovery/late-modules.sh': '/system/bin/sheng-recovery-late-modules',
        }.items():
            assert actual[installed] == packaged['startup_sources'][relative]

    log_path = '/dev/sheng-recovery-hardware.log' if args.revision >= 56 else '/tmp/sheng-recovery-hardware.log'
    starter = read('cat ' + log_path)
    assert re.search(r'/sys/class/remoteproc/remoteproc\d+: running', starter)
    # r56 attempts firmware startup before coldboot creates the modem node.
    # Preserve the failed early attempt as evidence and require a clean final
    # attempt; never count a requested service or bootconfig as successful work.
    attempts = [part for part in starter.split('sheng recovery hardware:') if part.strip()]
    assert attempts and not re.search(r'unavailable|not started|not starting', attempts[-1])
    early_failures = [part.strip() for part in attempts[:-1]
                      if re.search(r'unavailable|not started|not starting', part)]
    if early_failures:
        assert args.revision >= 56
        assert all('ADSP firmware unavailable; not starting a partially supplied DSP' in part
                   for part in early_failures)
    remoteprocs = read('for p in /sys/class/remoteproc/remoteproc*; do '
                       'echo "$p"; cat "$p/name" "$p/state"; done')
    assert re.search(r'[^\n]*remoteproc-adsp\nrunning', remoteprocs)
    battery_text = read('cat /sys/class/power_supply/battery/uevent')
    battery = dict(line.split('=', 1) for line in battery_text.splitlines() if '=' in line)
    assert battery['POWER_SUPPLY_PRESENT'] == '1'
    level = int(battery['POWER_SUPPLY_CAPACITY'])
    assert 0 <= level <= 100
    assert int(battery['POWER_SUPPLY_VOLTAGE_NOW']) > 2500000
    assert -100 < int(battery['POWER_SUPPLY_TEMP']) < 1000
    dmesg = read('dmesg')
    (REVIEW / ('r%d-dmesg.txt' % args.revision)).write_text(dmesg + '\n')
    recovery_log = read('cat /tmp/recovery.log')
    (REVIEW / ('r%d-recovery.log' % args.revision)).write_text(recovery_log + '\n')
    touch_log = read('cat /tmp/sheng-touch-runtime.log')
    (REVIEW / ('r%d-touch-runtime.log' % args.revision)).write_text(touch_log + '\n')
    assert read('getprop init.svc.vendor.health-recovery') == 'running'
    assert read('getprop init.svc.sheng-recovery-touch') == 'running'
    touch_exits = [line for line in dmesg.splitlines()
                   if "Service 'sheng-recovery-touch'" in line and
                   ('exited' in line or 'signal' in line)]
    assert not touch_exits, touch_exits
    firmware_denials = [line for line in dmesg.splitlines()
                       if 'avc:' in line and ('firmware_class' in line or
                                              'vendor_sysfs_sheng_firmware_path' in line)]
    assert not firmware_denials, firmware_denials
    assert not re.search(r'Direct firmware load for adsp.*failed', dmesg)
    adsp_up = re.search(r'\[\s*([\d.]+)\].*remote processor .*remoteproc-adsp is now up', dmesg)
    health = re.search(r'\[\s*([\d.]+)\] healthd: battery l=(\d+) v=(\d+) t=([-\d.]+)', dmesg)
    assert adsp_up and health and int(health[3]) > 2500

    receipt = {
        'date_utc': datetime.now(timezone.utc).isoformat(),
        'boot_id': read('cat /proc/sys/kernel/random/boot_id'),
        'serial': 'ca10ede3', 'slot': 'a', 'revision': args.revision,
        'installed_image_readback_verified': True,
        'embedded_policy_and_script_match_current_scoped_build': True,
        'recovery_b_boot_a_dtbo_a_unchanged': True,
        'recovery_boot_global_selinux': 'Enforcing',
        'existing_permissive_domains': compiled['existing_permissive_domains'],
        'new_permissive_domains': [],
        'firmware_path_init_denials': firmware_denials,
        'adsp_automatically_running': True,
        'early_hardware_start_failures': early_failures,
        'final_hardware_start_attempt_passed': True,
        'adsp_up_seconds_since_kernel_boot': float(adsp_up[1]),
        'first_valid_healthd_seconds_since_kernel_boot': float(health[1]),
        'battery_level': level, 'battery_properties': battery,
        'health_service_and_touch_service_running': True,
        'touch_service_startup_exits': touch_exits,
        'hashes': actual,
        'full_product_build_passed': False,
        'nonfull_battery_percentage_verified': level < 100,
        'user_recovery_display_observation': 'pending',
        'recovery_entry_black_screen_fixed': None,
    }
    if args.revision >= 55:
        assert 'Trying again for reinitializing battery info' not in recovery_log
        menu = re.search(r'first menu submitted at boot ([\d.]+)s', recovery_log)
        real_battery = re.search(r'real battery \d+% at boot ([\d.]+)s', recovery_log)
        assert menu and real_battery
        receipt['first_menu_submitted_boot_seconds'] = float(menu[1])
        receipt['first_real_battery_ui_boot_seconds'] = float(real_battery[1])
        receipt['ui_battery_retry_lock_removed'] = True
        receipt['menu_submitted_before_first_battery_read'] = float(menu[1]) < float(real_battery[1])
        (REVIEW / ('r%d-recovery.log' % args.revision)).write_text(recovery_log + '\n')
    if args.revision >= 56:
        bootconfig = read('cat /proc/bootconfig')
        parallel_mode = 'false' if args.revision >= 59 else 'conservative'
        assert 'androidboot.load_modules_parallel = "' + parallel_mode + '"' in bootconfig
        assert 'battery events enabled' in recovery_log
        baseline = (REVIEW / 'r55-dmesg.txt').read_text(encoding='utf-8-sig')
        expected_modules = {Path(name).stem.replace('-', '_') for name in re.findall(r'Loaded kernel module (\S+\.ko)', baseline)}
        actual_modules = {line.split()[0] for line in read('cat /proc/modules').splitlines()}
        assert expected_modules and expected_modules <= actual_modules, sorted(expected_modules - actual_modules)
        receipt['r55_loaded_modules_retained'] = len(expected_modules)
        loading = set()
        peak_loading = 0
        for line in dmesg.splitlines():
            event = re.search(r'init: (Loading module|Loaded kernel module) (\S+\.ko)', line)
            if not event:
                continue
            if event[1] == 'Loading module':
                loading.add(event[2])
                peak_loading = max(peak_loading, len(loading))
            else:
                loading.discard(event[2])
        receipt['conservative_parallel_module_loading_requested'] = parallel_mode == 'conservative'
        receipt['parallel_module_loading_observed'] = peak_loading > 1
        receipt['peak_concurrent_module_loads'] = peak_loading
        receipt['battery_uevent_monitor_enabled'] = True
        receipt['bootconfig'] = bootconfig
        if args.revision >= 57:
            layout = packaged['module_layout']
            assert read('readlink /lib/modules/' + layout['release']) == '.'
            assert read('find /lib/modules -maxdepth 1 -type d') == '/lib/modules'
            module_hashes = hashes(read('sha256sum /lib/modules/*.ko'))
            for name, digest in layout['files'].items():
                if name.endswith('.ko'):
                    assert module_hashes['/lib/modules/' + name] == digest, name
            if parallel_mode == 'conservative':
                assert peak_loading > 1, 'The boot must actually load modules concurrently'
            else:
                assert peak_loading == 1, 'Preserve the original sequential driver order'
                receipt['sequential_module_loading_verified'] = True
            flat_load = re.search(r'\[\s*([\d.]+)\].*init: Loaded (\d+) modules from /lib/modules$', dmesg, re.M)
            late = layout.get('late_modules', [])
            assert flat_load and int(flat_load[2]) == len(expected_modules) - len(late)
            receipt['flat_module_directory_and_release_symlink_verified'] = True
            receipt['all_packaged_module_hashes_verified'] = layout['module_count']
            receipt['first_stage_module_loading_completed_boot_seconds'] = float(flat_load[1])
            if late:
                assert read('getprop init.svc.sheng-recovery-late-modules') == 'stopped'
                late_log = read('cat /dev/sheng-recovery-late-modules.log')
                assert 'late block2mtd exit 0' in late_log
                assert 'Loaded kernel module /lib/modules/block2mtd.ko' not in dmesg
                assert 'block2mtd: /dev/block/sda19' in read('cat /proc/mtd')
                receipt['oops_module_loaded_after_coldboot'] = True
                receipt['first_stage_deferred_modules'] = late
                receipt['late_module_log'] = late_log
    if args.revision >= 59:
        uptime = float(read('cat /proc/uptime').split()[0])
        time.sleep(max(0.0, 20.0 - uptime))
        assert read('cat /proc/sys/kernel/random/boot_id') == receipt['boot_id']
        late_dmesg = read('dmesg')
        (REVIEW / ('r%d-late-dmesg.txt' % args.revision)).write_text(late_dmesg + '\n')
        late_exits = [line for line in late_dmesg.splitlines()
                      if "Service 'sheng-recovery-touch'" in line and
                      ('exited' in line or 'signal' in line)]
        assert not late_exits, late_exits
        assert read('getprop init.svc.sheng-recovery-touch') == 'running'
        receipt['touch_service_no_startup_exit_through_boot_seconds'] = float(
            read('cat /proc/uptime').split()[0])
    (REVIEW / ('r%d-runtime.json' % args.revision)).write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
