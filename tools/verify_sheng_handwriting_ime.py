#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read back the original preinstalled handwriting IME and its active Android registration."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[4]
    adb = workspace/'tools/platform-tools/adb.exe'
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    data = args.package.read_bytes()
    package = json.loads(data)
    assert package['kind'] == 'targeted-handwriting-ime-preinstall'
    assert package['complete_avb_chain_verified'] and package['ime_original_signature_preserved']
    assert set(package['entries']) == {'product'}
    relative = 'app/ShengSogouIme/ShengSogouIme.apk'
    assert set(package['entries']['product']) == {relative}
    expected_hash = package['entries']['product'][relative]['sha256']
    name = 'com.sohu.inputmethod.sogouoem'
    component = name+'/.SogouIME'
    system_path = '/product/'+relative
    receipt = dict(started_utc=datetime.now(timezone.utc).isoformat(), passed=False, read_only=True,
                   serial='ca10ede3', package_sha256=hashlib.sha256(data).hexdigest(), commands=[])

    def shell(label, command):
        result = subprocess.run([str(adb), '-s', 'ca10ede3', 'shell', command], capture_output=True, timeout=55)
        (output/(label+'.stdout')).write_bytes(result.stdout)
        (output/(label+'.stderr')).write_bytes(result.stderr)
        receipt['commands'].append(dict(command=command, returncode=result.returncode))
        result.check_returncode()
        return result.stdout.decode(errors='strict').strip()

    def identity(label):
        result = shell(label, 'getprop ro.product.device; getprop ro.boot.slot_suffix; '
                       'getprop sys.boot_completed; getenforce; uname -r; id -u; '
                       'cat /proc/sys/kernel/random/boot_id').splitlines()
        assert result[:6] == ['sheng', '_a', '1', 'Enforcing', '5.15.220-gf9ca2b71f672', '0']
        assert len(result) == 7
        return result

    try:
        receipt['before'] = identity('before-state')
        assert shell('preinstalled-hash', 'sha256sum '+system_path).split()[0] == expected_hash
        labels = shell('preinstalled-metadata', 'stat -c "%a %u %g %C" '+system_path).split()
        assert labels == ['644', '0', '0', 'u:object_r:system_file:s0'], labels
        paths = shell('loaded-path', 'pm path '+name).splitlines()
        assert len(paths) == 1 and paths[0].startswith('package:/')
        active = paths[0][len('package:'):]
        assert shell('loaded-hash', 'sha256sum '+shlex.quote(active)).split()[0] == expected_hash
        dump = shell('package-registration', 'dumpsys package '+name)
        assert '/product/app/ShengSogouIme' in dump
        assert re.search(r'\bflags=\[.*\bSYSTEM\b.*\]', dump), 'PackageManager must recognize a system app'
        methods = shell('input-methods', 'ime list -a')
        matches = [line for line in methods.splitlines() if 'mId='+component+' ' in line]
        assert len(matches) == 1 and 'mSupportsStylusHandwriting=true' in matches[0]
        assert shell('default-input-method', 'settings get secure default_input_method') == component
        assert component in shell('enabled-input-methods', 'settings get secure enabled_input_methods')
        for key in ('stylus_handwriting_enabled', 'show_ime_with_hard_keyboard'):
            assert shell(key, 'settings get secure '+key) == '1'
        receipt['after'] = identity('after-state')
        assert receipt['before'] == receipt['after'] and args.package.read_bytes() == data
        receipt.update(passed=True, preinstalled_path=system_path, active_path=active,
                       sha256=expected_hash, original_signature_preserved=True,
                       system_app_registered=True, stylus_handwriting_supported=True,
                       default_input_method=component, user_data_reset=False)
    except BaseException as error:
        receipt['error'] = repr(error)
        raise
    finally:
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        (output/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps({key: receipt[key] for key in ('passed', 'preinstalled_path', 'active_path',
                                                   'stylus_handwriting_supported')}, indent=2))


if __name__ == '__main__':
    main()
