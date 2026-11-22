#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read back the installed r65 service or sealed r66 UI update without changing hardware state."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import struct
import subprocess

INSTANCE = 'vendor.lineage.sheng.stylus.IPenController/default'
APP = 'org.lineageos.sheng.stylus'
DAEMON = 'vendor.lineage.sheng.stylus-service'
JOURNAL = '/data/user_de/0/' + APP + '/files/pro-input-lease.json'
INTENT = b'sheng-stylus-connection-intent-v1\n'
EXPECTED_CONTEXTS = {
    'daemon': 'u:r:vendor_sheng_stylus:s0',
    'app': 'u:r:sheng_stylus_app:s0',
}


def parcel_bytes(output):
    """Decode toybox service's single-line and offset-prefixed Parcel forms."""
    if 'Parcel(' not in output or 'Error' in output:
        raise ValueError('The Binder metadata transaction did not return a Parcel')
    words = []
    for line in output.splitlines():
        payload = line.split("'", 1)[0]
        payload = re.sub(r'^\s*0x[0-9a-fA-F]+:\s*', '', payload)
        words.extend(re.findall(r'\b[0-9a-fA-F]{8}\b', payload))
    raw = b''.join(struct.pack('<I', int(word, 16)) for word in words)
    if len(raw) < 8 or struct.unpack_from('<i', raw)[0] != 0:
        raise ValueError('The Binder metadata transaction returned an exception')
    return raw


def main():
    workspace = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', type=Path, default=workspace/'tools/platform-tools/adb.exe')
    parser.add_argument('--package', type=Path,
                        default=workspace/'artifacts/system-hardware-followup-sheng-r65/build-result.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    commands = []
    receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), serial='ca10ede3',
                   passed=False, installed=False, device_changed=False,
                   hardware_writing_tested=False, native_crash_auto_recovery_passed=False)

    def call(label, *arguments, checked=True):
        argv = [str(args.adb), '-s', 'ca10ede3', *arguments]
        result = subprocess.run(argv, capture_output=True, timeout=55)
        (output/(label+'.stdout')).write_bytes(result.stdout)
        (output/(label+'.stderr')).write_bytes(result.stderr)
        commands.append(dict(argv=argv, returncode=result.returncode, output=label))
        (output/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
        if checked:
            result.check_returncode()
        return result

    def text_call(label, command):
        return call(label, 'shell', command).stdout.decode(errors='strict').strip()

    def identity(label):
        command = ('getprop ro.product.device; getprop ro.boot.slot_suffix; '
                   'getprop sys.boot_completed; getenforce; uname -r; id -u; '
                   'cat /proc/sys/kernel/random/boot_id')
        values = text_call(label, command).splitlines()
        expected = ['sheng', '_a', '1', 'Enforcing', '5.15.220-gf9ca2b71f672', '0']
        if values[:6] != expected or len(values) != 7:
            raise ValueError('Unexpected live Android/slot/kernel/SELinux state: '+repr(values))
        return dict(zip(('device', 'slot', 'boot_completed', 'selinux', 'kernel', 'uid', 'boot_id'), values))

    def process(label, name):
        ids = text_call(label+'-pid', 'pidof '+name).split()
        if len(ids) != 1 or not re.fullmatch(r'[1-9][0-9]*', ids[0]):
            raise ValueError('Expected one live '+label+' process')
        pid = ids[0]
        context = text_call(label+'-context', 'cat /proc/'+pid+'/attr/current').rstrip('\0')
        if context != EXPECTED_CONTEXTS[label]:
            raise ValueError('Unexpected '+label+' process context: '+context)
        status = text_call(label+'-status', 'cat /proc/'+pid+'/status')
        uid = re.search(r'^Uid:\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$', status, re.MULTILINE)
        if uid is None or set(uid.groups()) != {'1000'}:
            raise ValueError('Unexpected '+label+' UID')
        return dict(pid=int(pid), context=context, uid=1000)

    try:
        package_bytes = args.package.read_bytes()
        package = json.loads(package_bytes)
        ui_update = package.get('revision') == 66
        controls_update = package.get('targeted_controls_build_passed') is True
        ime_included = package.get('preinstalled_ime_included') is True
        service_package = package
        if ui_update:
            required = ('complete_avb_chain_verified', 'policy_and_vintf_inputs_unchanged',
                        'native_service_unchanged', 'systemui_unchanged', 'targeted_ui_build_passed')
            if package.get('baseline_revision') != 65 or not all(package.get(key) is True for key in required):
                raise ValueError('The sealed r66 UI update and unchanged native service are required')
            baseline_bytes = (workspace/'artifacts/system-hardware-followup-sheng-r65/build-result.json').read_bytes()
            if hashlib.sha256(baseline_bytes).hexdigest() != package['baseline_manifest_sha256']:
                raise ValueError('The r66 native-service baseline manifest changed')
            service_package = json.loads(baseline_bytes)
            expected_entries = {'app/ShengPenSettings/ShengPenSettings.apk',
                                'priv-app/ShengStylus/ShengStylus.apk'}
            if ime_included:
                expected_entries.add('app/ShengSogouIme/ShengSogouIme.apk')
            if (set(package['entries']) != {'system_ext'}
                    or set(package['entries']['system_ext']) != expected_entries):
                raise ValueError('Unexpected files in the r66 UI update')
        if (service_package['revision'] != 65 or service_package['baseline_revision'] != 64
                or not (service_package.get('normal_module_build_passed') or
                        (service_package.get('qualified_module_build_passed') and service_package.get('targeted_module_build_passed')))
                or not service_package['complete_avb_chain_verified']
                or not service_package['pen_permanent_service_preinstalled']):
            raise ValueError('The sealed frozen-service r65 package is required')
        installed_entries = {part: dict(entries) for part, entries in service_package['entries'].items()}
        if ui_update:
            for part, entries in package['entries'].items():
                installed_entries.setdefault(part, {}).update(entries)
        receipt['revision'] = package['revision']
        receipt['package_sha256'] = hashlib.sha256(package_bytes).hexdigest()
        receipt['before'] = identity('before-state')
        if text_call('init-service', 'getprop init.svc.vendor.sheng-stylus') != 'running':
            raise ValueError('The installed init service is not running')
        receipt['processes'] = {label: process(label, name)
                                for label, name in (('daemon', DAEMON), ('app', APP))}
        remote_files = {}
        for part, entries in installed_entries.items():
            if part not in ('system', 'system_ext', 'product', 'vendor'):
                raise ValueError('Unexpected installed partition')
            for relative, entry in entries.items():
                if (not re.fullmatch(r'[A-Za-z0-9_./+-]+', relative)
                        or relative.startswith('/') or '..' in Path(relative).parts
                        or not re.fullmatch(r'[0-9a-f]{64}', entry['sha256'])):
                    raise ValueError('Invalid declared installed file')
                remote_files['/'+part+'/'+relative] = entry['sha256']
        if not remote_files:
            raise ValueError('Installed file qualification is missing')
        hashes = text_call('installed-file-hashes', 'sha256sum '+' '.join(remote_files)).splitlines()
        actual = {}
        for line in hashes:
            digest, name = line.split()
            actual[name] = digest
        if actual != remote_files:
            raise ValueError('Installed files differ from the sealed candidate')
        receipt['installed_file_hashes'] = actual
        labels = text_call('file-contexts', 'ls -Zd /dev/sheng-stylus '
                           '/vendor/bin/hw/'+DAEMON+' '+str(Path(JOURNAL).parent))
        for context in ('u:object_r:vendor_sheng_stylus_runtime_file:s0',
                        'u:object_r:vendor_sheng_stylus_exec:s0',
                        'u:object_r:sheng_stylus_app_data_file:s0'):
            if context not in labels:
                raise ValueError('Missing runtime/executable/data label: '+context)
        version = parcel_bytes(text_call('binder-version', 'service call '+INSTANCE+' 16777215'))
        if struct.unpack_from('<i', version, 4)[0] != 1:
            raise ValueError('Unexpected Binder interface version')
        raw_hash = parcel_bytes(text_call('binder-hash', 'service call '+INSTANCE+' 16777214'))
        length = struct.unpack_from('<i', raw_hash, 4)[0]
        if length != 40 or len(raw_hash) < 8+2*(length+1) or raw_hash[8+2*length:10+2*length] != b'\0\0':
            raise ValueError('Invalid Binder interface hash Parcel')
        interface_hash = raw_hash[8:8+2*length].decode('utf-16-le')
        if interface_hash != service_package['frozen_api_hash']:
            raise ValueError('Installed Binder interface hash differs from frozen V1')
        receipt.update(interface_version=1, interface_hash=interface_hash)
        journal = json.loads(call('input-journal', 'exec-out', 'cat', JOURNAL).stdout)
        boot_count = int(text_call('boot-count', 'settings get global boot_count'))
        if (journal['version'] != 2 or journal['boot'] != boot_count
                or not isinstance(journal['entries'], list)):
            raise ValueError('The current input restoration journal is not valid')
        receipt['input_journal'] = journal
        marker = call('native-lease', 'exec-out', 'cat', '/dev/sheng-stylus/lease', checked=False)
        if marker.returncode == 0:
            if marker.stdout != INTENT:
                raise ValueError('Unexpected boot-local native lease marker')
            receipt['native_lease_marker_present'] = True
        elif b'No such file or directory' in marker.stderr+marker.stdout:
            receipt['native_lease_marker_present'] = False
        else:
            raise ValueError('The native lease marker could not be read')
        text_call('package-manager', 'dumpsys package '+APP)
        if ui_update:
            receipt['loaded_apks'] = {}
            expected_apps = [(APP, 'priv-app/ShengStylus/ShengStylus.apk'),
                             ('org.lineageos.sheng.pen', 'app/ShengPenSettings/ShengPenSettings.apk')]
            if ime_included:
                expected_apps.append(('com.sohu.inputmethod.sogouoem', 'app/ShengSogouIme/ShengSogouIme.apk'))
            for name, relative in expected_apps:
                paths = text_call(name+'-loaded-path', 'pm path '+name).splitlines()
                if len(paths) != 1 or not paths[0].startswith('package:/'):
                    raise ValueError('Expected exactly one loaded APK for '+name)
                remote = paths[0][len('package:'):]
                digest = text_call(name+'-loaded-hash', 'sha256sum '+shlex.quote(remote)).split()[0]
                if digest != package['entries']['system_ext'][relative]['sha256']:
                    raise ValueError('Loaded APK differs from r66: '+name)
                dump = text_call(name+'-package', 'dumpsys package '+name).split('Hidden system packages:')[0]
                version_code = int(re.search(r'\bversionCode=(\d+)', dump)[1])
                required_permissions = (('android.permission.INTERNAL_SYSTEM_WINDOW',) if name == APP
                    else ('org.lineageos.sheng.stylus.READ_CHARGING',) if name == 'org.lineageos.sheng.pen' else ())
                if controls_update and name == APP:
                    required_permissions += ('android.permission.INJECT_EVENTS', 'android.permission.MONITOR_INPUT')
                if controls_update and name == 'org.lineageos.sheng.pen':
                    required_permissions += ('android.permission.WRITE_SECURE_SETTINGS',)
                if name == APP and version_code < 4:
                    required_permissions += ('android.permission.POST_NOTIFICATIONS',)
                for permission in required_permissions:
                    if not re.search(re.escape(permission)+r': granted=true\b', dump):
                        raise ValueError('Missing charging permission '+permission+' for '+name)
                receipt['loaded_apks'][name] = dict(path=remote, sha256=digest,
                    version_code=version_code, version_name=re.findall(r'\bversionName=(\S+)', dump),
                    permissions_verified=list(required_permissions))
            if ime_included:
                methods = text_call('handwriting-input-method', 'ime list -a')
                sogou = [line for line in methods.splitlines() if 'mId=com.sohu.inputmethod.sogouoem/.SogouIME ' in line]
                if len(sogou) != 1 or 'mSupportsStylusHandwriting=true' not in sogou[0]:
                    raise ValueError('The preinstalled input method does not expose stylus handwriting')
                receipt['preinstalled_handwriting_ime_verified'] = True
            if receipt['loaded_apks'][APP]['version_code'] >= 4:
                notifications = text_call('charging-notification-absence', 'dumpsys notification --noredact')
                active = [line for line in notifications.splitlines()
                          if 'NotificationRecord(' in line and 'pkg='+APP+' ' in line]
                if active:
                    raise ValueError('The current pen build must not post notifications: '+repr(active))
                receipt['notification_drawer_clear'] = True
            status = text_call('charge-provider', 'content query --uri content://org.lineageos.sheng.stylus.charging/status')
            match = re.search(r'\bstate=(UNKNOWN|DETACHED|NOT_CHARGING|WAITING|CHARGING|FULL|MISALIGNED), level=(-?\d+), address=(\S+)', status)
            if match is None or not -1 <= int(match[2]) <= 100:
                raise ValueError('Charging provider returned invalid data: '+status)
            receipt['charging_provider'] = dict(state=match[1], level=int(match[2]), address=match[3])
        text_call('input-state', 'dumpsys input')
        text_call('display-state', 'dumpsys display')
        text_call('dock-state', 'cat /sys/class/qcom-battery/pen_hall3 /sys/class/qcom-battery/pen_hall4')
        logs = call('boot-logcat', 'logcat', '-b', 'all', '-d', '-v', 'threadtime').stdout.decode(errors='replace')
        denials = [line for line in logs.splitlines() if 'avc:' in line and 'denied' in line
                   and ('sheng_stylus' in line or 'ShengStylus' in line or 'sheng-stylus' in line
                        or 'ShengPen' in line or 'sheng.pen' in line)]
        receipt['related_avcs'] = denials
        if denials:
            raise ValueError('The current boot contains stylus-related SELinux denials')
        receipt['stylus_logs'] = [line for line in logs.splitlines()
                                 if 'ShengStylus' in line or 'sheng-stylus' in line or 'ShengPenCharge' in line]
        if ui_update:
            errors = [line for line in logs.splitlines()
                      if 'ShengPenCharge' in line and 'Charging feedback unavailable' in line]
            receipt['charging_feedback_errors'] = errors
            if errors:
                raise ValueError('Charging feedback reported a runtime failure')
        receipt['after'] = identity('after-state')
        if receipt['before'] != receipt['after']:
            raise ValueError('The device rebooted or changed during readback')
        for label, name in (('daemon', DAEMON), ('app', APP)):
            if text_call(label+'-pid-after', 'pidof '+name).split() != [str(receipt['processes'][label]['pid'])]:
                raise ValueError('The '+label+' process restarted during readback')
        if args.package.read_bytes() != package_bytes:
            raise ValueError('The sealed package changed during readback')
        receipt.update(passed=True, installed=True, current_boot_processes_stable=True,
                       installed_contexts_verified=True, input_journal_metadata_verified=True)
    except BaseException as error:
        receipt['error'] = repr(error)
        raise
    finally:
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        (output/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(dict(passed=True, installed=True, interface_version=1,
                         interface_hash=receipt['interface_hash'], output=str(output),
                         hardware_writing_tested=False), indent=2))


if __name__ == '__main__':
    main()
