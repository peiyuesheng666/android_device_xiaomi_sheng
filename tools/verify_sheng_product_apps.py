#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify product app paths, preserved identities/permissions, and handwriting registration."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shlex
import subprocess

from flash_sheng_product_apps import sha


def avc_signature(line):
    access = re.search(r'avc:\s+denied\s+\{([^}]+)\}', line)
    if not access: return None
    fields = [','.join(sorted(access[1].split()))]
    for key in ('scontext', 'tcontext', 'tclass'):
        value = re.search(r'\b'+key+r'=(\S+)', line)
        if not value: return None
        fields.append(value[1])
    obj = re.search(r'\b(?:path|name)=("[^"\n]*"|\S+)', line)
    fields.append(obj[1] if obj else '')
    return tuple(fields)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--flash-receipt', type=Path, required=True)
    parser.add_argument('--baseline-runtime', type=Path, required=True,
                        help='Successful runtime receipt for the exact previously installed package')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[4]
    adb = workspace/'tools/platform-tools/adb.exe'
    package = json.loads(args.package.read_text())
    package_hash = sha(args.package)
    flash = json.loads(args.flash_receipt.read_text())
    assert package['kind'] in ('product-app-layout', 'product-pen-ui', 'codec2-service-update',
                               'vendor-runtime-update', 'ape-extractor-update') and flash['completed']
    assert flash['package_sha256'] == package_hash and len(flash['postboot_partitions_verified']) == 14
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    receipt = dict(started_utc=datetime.now(timezone.utc).isoformat(), passed=False, read_only=True,
                   package_sha256=package_hash, applications={}, commands=[], user_data_reset=False)
    baseline_runtime = json.loads(args.baseline_runtime.read_text())
    assert baseline_runtime['passed']

    def parent_manifest(child):
        relative = Path(child['baseline_manifest'])
        assert not relative.is_absolute() and '..' not in relative.parts
        parent = workspace / relative
        assert sha(parent) == child['baseline_manifest_sha256']
        return json.loads(parent.read_text())

    def preserves_app_partitions(child):
        assert child['kind'] in ('codec2-service-update', 'vendor-runtime-update', 'ape-extractor-update')
        assert child['product_apps_unchanged']
        assert child['complete_avb_chain_verified'] and not child['removals']
        before = {row['partition']: row['sha256'] for row in child['baseline_partitions']}
        after = {row['partition']: row['sha256'] for row in child['files'] + child['unchanged_partition_files']}
        assert set(before) == set(after)
        allowed_changes = {'vendor', 'vbmeta'}
        if child['kind'] == 'ape-extractor-update':
            allowed_changes.update(('system_ext', 'vbmeta_system'))
            library = 'lib64/extractors/libshengapeextractor.so'
            assert set(child['entries']) == {'vendor', 'system_ext'}
            assert set(child['entries']['system_ext']) == {library}
            stage = child['partition_reports']['system_ext']
            assert stage['metadata_preserved'] and stage['changed_files'] == [library]
            assert not stage['removed_files']
            assert set(child['entries']['vendor']) == {
                'etc/media_codecs_c2_audio.xml', 'etc/media_codecs_c2_audio_base.xml'}
        else:
            assert set(child['entries']) == {'vendor'}
        assert all(before[part] == after[part] for part in before if part not in allowed_changes)

    ancestor = package
    while ancestor['baseline_manifest_sha256'] != baseline_runtime['package_sha256']:
        ancestor = parent_manifest(ancestor)
        preserves_app_partitions(ancestor)
    baseline_log = args.baseline_runtime.parent/'boot-logcat.stdout'
    known_denials = {avc_signature(line) for line in baseline_log.read_text(errors='replace').splitlines()
                     if 'avc:' in line and 'denied' in line}
    known_denials.discard(None)
    receipt['baseline_runtime_sha256'] = sha(args.baseline_runtime)
    receipt['baseline_log_sha256'] = sha(baseline_log)
    layout = package
    layers = []
    while layout['kind'] in ('product-pen-ui', 'codec2-service-update', 'vendor-runtime-update', 'ape-extractor-update'):
        if layout['kind'] == 'product-pen-ui':
            layers.append(layout['entries']['product'])
        else:
            preserves_app_partitions(layout)
        layout = parent_manifest(layout)
    assert layout['kind'] == 'product-app-layout'
    installed_entries = dict(layout['entries']['product'])
    for layer in reversed(layers): installed_entries.update(layer)

    def call(label, *arguments):
        result = subprocess.run([str(adb), '-s', 'ca10ede3', *arguments], capture_output=True, timeout=55)
        (out/(label+'.stdout')).write_bytes(result.stdout)
        (out/(label+'.stderr')).write_bytes(result.stderr)
        receipt['commands'].append(dict(arguments=list(arguments), returncode=result.returncode))
        result.check_returncode()
        return result.stdout.decode(errors='replace').strip()
    def shell(label, command): return call(label, 'shell', command)
    def identity(label):
        values = shell(label, 'getprop ro.product.device; getprop ro.boot.slot_suffix; '
                       'getprop sys.boot_completed; getenforce; uname -r; id -u; '
                       'cat /proc/sys/kernel/random/boot_id').splitlines()
        assert values[:6] == ['sheng', '_a', '1', 'Enforcing', '5.15.220-gf9ca2b71f672', '0']
        assert len(values) == 7
        return values
    def permissions(dump):
        active = dump.split('Hidden system packages:')[0]
        return set(re.findall(r'^\s+([a-zA-Z][\w.]+): granted=true\b', active, re.M))

    try:
        receipt['before'] = identity('before-state')
        files = {'/product/'+p: row['sha256'] for p, row in installed_entries.items()}
        rows = shell('installed-file-hashes', 'sha256sum '+' '.join(map(shlex.quote, files))).splitlines()
        assert {name: digest for digest, name in map(str.split, rows)} == files
        old_paths = ['/system_ext/'+p for p in layout['removals']['system_ext']]
        shell('old-paths-absent', 'for p in '+' '.join(map(shlex.quote, old_paths))+
              '; do if [ -e "$p" ]; then printf "%s\\n" "$p"; exit 1; fi; done')
        for app in package['applications']:
            name, module = app['package'], app['module']
            declared_path = '/product/'+app['path']
            paths = shell(module+'-path', 'pm path '+name).splitlines()
            assert len(paths) == 1 and paths[0].startswith('package:/'), name
            active_path = paths[0][len('package:'):]
            if app.get('new_source'):
                assert active_path == declared_path or active_path.startswith('/data/app/'), name
            else: assert active_path == declared_path, name
            digest = shell(module+'-active-hash', 'sha256sum '+shlex.quote(active_path)).split()[0]
            assert digest == files[declared_path], name
            before_path = args.flash_receipt.parent/(module+'-before.txt')
            if not before_path.exists():
                assert package['kind'] in ('codec2-service-update', 'vendor-runtime-update', 'ape-extractor-update')
                before_path = args.baseline_runtime.parent/(module+'-package.stdout')
            before = before_path.read_text()
            after = shell(module+'-package', 'dumpsys package '+name)
            assert '/product/'+str(Path(app['path']).parent).replace('\\', '/') in after
            old_uid = re.search(r'\b(?:appId|userId)=(\d+)', before)
            new_uid = re.search(r'\b(?:appId|userId)=(\d+)', after)
            assert old_uid and new_uid, 'PackageManager did not expose the application ID: '+name
            assert old_uid[1] == new_uid[1], 'Application UID changed: '+name
            missing = permissions(before)-permissions(after)
            assert not missing, 'Permissions lost by '+name+': '+repr(sorted(missing))
            assert re.search(r'\bflags=\[.*\bSYSTEM\b.*\]', after), name
            if app['path'].startswith('priv-app/'):
                assert re.search(r'\bprivateFlags=\[.*\bPRIVILEGED\b.*\]', after), name
            metadata = shell(module+'-metadata', 'stat -c "%a %u %g %C" '+declared_path).split()
            assert metadata == ['644', '0', '0', 'u:object_r:system_file:s0'], name
            receipt['applications'][module] = dict(package=name, path=declared_path, active_path=active_path,
                uid=int(new_uid[1]), sha256=digest, existing_grants_preserved=True)
        component = 'com.sohu.inputmethod.sogouoem/.SogouIME'
        methods = shell('input-methods', 'ime list -a')
        lines = [line for line in methods.splitlines() if 'mId='+component+' ' in line]
        assert len(lines) == 1 and 'mSupportsStylusHandwriting=true' in lines[0]
        assert shell('default-ime', 'settings get secure default_input_method') == component
        for key in ('stylus_handwriting_enabled', 'show_ime_with_hard_keyboard'):
            assert shell(key, 'settings get secure '+key) == '1'
        assert shell('pen-native', 'getprop init.svc.vendor.sheng-stylus') == 'running'
        pid = shell('pen-app-pid', 'pidof org.lineageos.sheng.stylus')
        assert re.fullmatch(r'[1-9][0-9]*', pid)
        assert shell('pen-app-domain', 'cat /proc/'+pid+'/attr/current').rstrip('\0') == 'u:r:sheng_stylus_app:s0'
        logs = call('boot-logcat', 'logcat', '-b', 'all', '-d', '-v', 'threadtime')
        denials = [line for line in logs.splitlines() if 'avc:' in line and 'denied' in line
                   and any(token in line.lower() for token in ('sheng', 'metok', 'com.xiaomi.aon'))]
        receipt['related_avcs'] = denials
        new_denials = [line for line in denials if avc_signature(line) not in known_denials]
        receipt['new_related_avcs'] = new_denials
        receipt['preexisting_related_avcs'] = [line for line in denials if avc_signature(line) in known_denials]
        assert not new_denials, 'New application-related SELinux denial after migration'
        crashes = call('crash-log', 'logcat', '-b', 'crash', '-d', '-v', 'threadtime')
        assert not any('Process: '+app['package']+',' in crashes for app in package['applications'])
        receipt['after'] = identity('after-state')
        assert receipt['before'] == receipt['after'] and sha(args.package) == package_hash
        receipt.update(passed=True, application_count=len(receipt['applications']),
                       old_copies_removed=True, handwriting_supported=True, original_apk_bytes_preserved=True)
    except BaseException as error:
        receipt['error'] = repr(error)
        raise
    finally:
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        (out/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps({key: receipt[key] for key in ('passed', 'application_count',
                      'old_copies_removed', 'handwriting_supported')}, indent=2))


if __name__ == '__main__':
    main()
