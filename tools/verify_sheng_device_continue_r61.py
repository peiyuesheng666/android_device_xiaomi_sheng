#!/usr/bin/env python3
"""Read back r61-r64 partitions and exercise real suspend statistics in Enforcing."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

WAKEUP_PARENTS = [
    '/sys/devices/platform/soc/soc:xm_battmngr/wakeup',
    '/sys/devices/platform/soc/soc:fingerprint_fpc/wakeup',
    '/sys/devices/platform/soc/soc:xiaomi_wifi_gpio/wakeup',
    '/sys/devices/platform/soc/8c0000.qcom,qupv3_2_geni_se/884000.i2c/i2c-5/5-004c/wakeup',
]
STATISTICS = ['name', 'active_count', 'last_change_ms', 'max_time_ms',
              'total_time_ms', 'active_time_ms', 'event_count', 'expire_count',
              'prevent_suspend_time_ms', 'wakeup_count']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--revision', type=int, choices=[61, 62, 63, 64], default=61)
    args = parser.parse_args()
    root = args.workspace.resolve(strict=True)
    work = args.output.resolve()
    work.mkdir(parents=True, exist_ok=False)
    manifest_path = root / f'artifacts/system-hardware-followup-sheng-r{args.revision}/build-result.json'
    manifest = json.loads(manifest_path.read_text())
    assert manifest['revision'] == args.revision and manifest['installed_qti_retained']
    assert manifest['qti_source_service_integrated'] is False
    commands = []
    result = dict(date_utc=datetime.now(timezone.utc).isoformat(), serial='ca10ede3',
                  revision=args.revision, passed=False, physical_double_tap_tested=False,
                  standby_fingerprint_tested=False, full_product_build_passed=False)

    def shell(command, name=None):
        value = subprocess.run([str(root / 'tools/platform-tools/adb.exe'), '-s',
                                'ca10ede3', 'shell', command], capture_output=True,
                               text=True, timeout=60)
        commands.append(dict(command=command, returncode=value.returncode,
                             stdout=value.stdout, stderr=value.stderr))
        (work / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        if name:
            (work / name).write_text(value.stdout + value.stderr)
        assert value.returncode == 0, value.stdout + value.stderr
        return value.stdout.strip()

    try:
        assert shell('getprop ro.product.device') == 'sheng'
        assert shell('getprop ro.boot.slot_suffix') == '_a'
        assert shell('getprop sys.boot_completed') == '1'
        assert shell('getenforce') == 'Enforcing'
        assert shell('id -u') == '0'
        result['boot_id'] = shell('cat /proc/sys/kernel/random/boot_id')
        hashes = {}
        logical = {'system', 'odm', 'product', 'system_ext', 'vendor', 'vendor_dlkm', 'system_dlkm'}
        allowed = logical | {'init_boot', 'boot', 'dtbo', 'recovery', 'vendor_boot', 'vbmeta', 'vbmeta_system'}
        entries = (manifest['files'] + manifest['unchanged_partition_files'] +
                   manifest['unchanged_boot_dependencies'])
        assert len({e['partition'] for e in entries}) == len(entries)
        for entry in entries:
            part = entry['partition']
            assert part in allowed and re.fullmatch('[0-9a-f]{64}', entry['sha256'])
            size = int(entry['bytes'])
            assert size > 0
            command = (f'sha256sum /dev/block/mapper/{part}_a' if part in logical else
                       f'head -c {size} /dev/block/by-name/{part}_a | sha256sum')
            digest = shell(command).split()[0]
            assert digest == entry['sha256'], part
            hashes[part] = digest
        result['partition_sha256'] = hashes
        qti = shell('sha256sum /vendor/bin/hw/vendor.qti.media.c2@1.0-service').split()[0]
        assert qti == manifest['retained_qti_sha256']
        ui = shell('sha256sum /system_ext/priv-app/SystemUI/SystemUI.apk').split()[0]
        assert ui == '33017b0d59e28da5db3e089a98f49601de508228a012392ee2d04c82cda3ccb1'
        for kind in ['single_tap', 'double_tap']:
            assert shell(f'getprop ro.vendor.sensors.xiaomi.{kind}') == 'false'
        for name in ['config_dozeTapSensorType', 'config_dozeDoubleTapSensorType']:
            assert shell(f'cmd overlay lookup android android:string/{name}') in ['', '""']
        assert shell('cmd overlay lookup android android:bool/config_supportDoubleTapWake') == 'true'
        sensors = shell('dumpsys sensorservice', 'sensorservice.txt')
        assert 'org.lineageos.sensor.single_tap' not in sensors
        assert 'org.lineageos.sensor.double_tap' not in sensors
        result['double_tap_to_wake'] = shell('settings get secure double_tap_to_wake')
        wakeups = {}
        for parent in WAKEUP_PARENTS:
            paths = shell(f'echo {parent}/wakeup*').split()
            assert paths and all(re.fullmatch(re.escape(parent) + r'/wakeup\d+', p) for p in paths)
            for path in paths:
                labels = shell('ls -Zd ' + path + ' ' + ' '.join(path + '/' + s for s in STATISTICS))
                assert len(labels.splitlines()) == 11 and all(
                    'u:object_r:sysfs_wakeup:s0' in line for line in labels.splitlines())
                wakeups[path] = shell('cat ' + path + '/name')
        fingerprint = shell('ls -Zd /sys/devices/platform/soc/soc:fingerprint_fpc')
        assert 'u:object_r:sysfs_fingerprint_sheng:s0' in fingerprint
        control = shell('ls -Zd /sys/devices/platform/soc/soc:fingerprint_fpc/wakeup_enable')
        assert 'u:object_r:sysfs_fingerprint_sheng:s0' in control, \
            'FPC control node was relabeled by the /wakeup character prefix'
        result['fingerprint_control_label_correct'] = True
        if args.revision >= 62:
            assert shell('getprop init.svc.vendor.fingerprint-default') == 'running'
            assert shell('getprop persist.vendor.sys.fp.vendor') == 'fpc'
            fingerprint_state = shell('dumpsys fingerprint', 'fingerprint-state.txt')
            deaths = re.search(r'HAL deaths since last reboot: (\d+)', fingerprint_state)
            assert deaths and int(deaths[1]) == 0, 'New fingerprint HAL death after boot'
            summary = next(json.loads(line) for line in fingerprint_state.splitlines()
                           if line.startswith('{') and '"prints"' in line)
            enrolled = sum(item['count'] for item in summary['prints'])
            assert enrolled > 0, 'The user-enrolled fingerprint was not retained'
            result['enrolled_fingerprint_count'] = enrolled
            result['fingerprint_hal_deaths'] = int(deaths[1])
        if args.revision >= 63:
            apk = '/system_ext/app/ShengPenSettings/ShengPenSettings.apk'
            assert shell('pm path org.lineageos.sheng.pen') == 'package:' + apk
            assert shell('sha256sum ' + apk).split()[0] == manifest['apk_sha256']
            package = shell('dumpsys package org.lineageos.sheng.pen', 'pen-package.txt')
            flags = re.search(r'^\s*flags=\[([^\]]+)\]', package, re.MULTILINE)
            assert flags and 'SYSTEM' in flags[1].split(), 'Pen page is not a preinstalled system app'
            if args.revision >= 64:
                assert 'versionCode=3 minSdk=1 targetSdk=37' in package
                assert 'versionName=1.2' in package, 'Old package parsing cache survived the update'
            # Include credential-protected activities while the owner is still locked.
            # Registration is distinct from launching the actual page after unlock.
            entries = shell('cmd package query-activities --brief --query-flags 786432 '
                            '-a com.android.settings.action.EXTRA_SETTINGS',
                            'extra-settings-entries.txt')
            assert 'org.lineageos.sheng.pen/.CompatibilityActivity' in entries
            launcher = shell('cmd package query-activities --brief --query-flags 786432 -a android.intent.action.MAIN '
                             '-c android.intent.category.LAUNCHER -p org.lineageos.sheng.pen')
            assert 'org.lineageos.sheng.pen/' not in launcher, 'Unexpected pen launcher entry'
            result.update(pen_settings_preinstalled=True, pen_settings_apk_sha256=manifest['apk_sha256'],
                          pen_settings_entry_resolved=True, pen_page_tested=False,
                          physical_pen_writing_tested=False)
        result['wakeup_instances'] = wakeups
        start = shell("date '+%m-%d %H:%M:%S.000'")
        assert re.fullmatch(r'\d\d-\d\d \d\d:\d\d:\d\d\.000', start)
        stats = shell('dumpsys suspend_control_internal', 'suspend-statistics.txt')
        assert 'WAKELOCK STATS' in stats
        for name in wakeups.values():
            assert name in stats, name
        log = shell(f"logcat -b all -d -T '{start}'", 'statistics-logcat.txt')
        assert not any('Permission denied' in line and ('wakeup' in line or 'SystemSuspend' in line)
                       for line in log.splitlines())
        assert not any('avc: denied' in line and 'scontext=u:r:system_suspend:s0' in line
                       for line in log.splitlines())
        shell('ps -A -Z', 'services.txt')
        result.update(passed=True, wakeup_statistics_readable=True,
                      unavailable_tap_sensors_removed=True, qti_retained_sha256=qti,
                      original_systemui_sha256=ui, manifest_sha256=hashlib.sha256(
                          manifest_path.read_bytes()).hexdigest())
    except BaseException as error:
        result['error'] = repr(error)
        raise
    finally:
        (work / 'runtime.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
