#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Cache actual A-slot VINTF/APEX/kernel inputs without changing the device."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', type=Path, required=True)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    host = args.rom.resolve(strict=True)/'out/host/linux-x86/bin'
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    commands = []
    receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), serial='ca10ede3',
                   passed=False, device_changed=False, hardware_tested=False, inputs={})

    def call(*arguments):
        argv = [str(args.adb), '-s', 'ca10ede3', *arguments]
        result = subprocess.run(argv, capture_output=True, timeout=55)
        commands.append(dict(argv=argv, returncode=result.returncode,
                             stderr=result.stderr.decode(errors='replace')))
        (output/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
        result.check_returncode()
        return result.stdout

    def state():
        command = ('getprop ro.product.device; getprop ro.boot.slot_suffix; getenforce; '
                   'uname -r; id -u; getprop ro.product.first_api_level; '
                   'getprop ro.boot.product.hardware.sku; getprop ro.boot.product.vendor.sku')
        values = call('shell', command).decode().splitlines()
        values = [value.strip() for value in values]
        expected = ['sheng', '_a', 'Enforcing', '5.15.220-gf9ca2b71f672',
                    '0', '34', 'sheng', 'kalama']
        if values != expected:
            raise RuntimeError('Live device does not match the sealed Android/5.15 baseline: '+repr(values))
        return dict(zip(('device', 'slot', 'selinux', 'kernel', 'uid',
                         'first_api', 'hardware_sku', 'vendor_sku'), values))

    def remote_hashes(paths):
        data = call('shell', 'sha256sum '+' '.join(paths)).decode().splitlines()
        result = {}
        for line in data:
            digest, name = line.split()
            if not re.fullmatch(r'[0-9a-f]{64}', digest):
                raise RuntimeError('Invalid live input hash')
            result[name] = digest
        if set(result) != set(paths):
            raise RuntimeError('Missing live input hashes')
        return result

    try:
        receipt['before'] = state()
        partitions = ('system', 'system_ext', 'product', 'vendor', 'odm')
        listing = call('shell', 'for d in /apex/*/etc/vintf '
                       + ' '.join('/'+part+'/etc/vintf' for part in partitions)+'; do '
                       'if [ -d "$d" ]; then find "$d" -type f; fi; done').decode().splitlines()
        paths = ['/proc/config.gz', '/apex/apex-info-list.xml']
        for name in listing:
            name = name.strip()
            path = PurePosixPath(name)
            pattern = r'/(?:apex/[A-Za-z0-9_.@+-]+|system|system_ext|product|vendor|odm)/etc/vintf/[A-Za-z0-9_./@+-]+'
            if '..' in path.parts or not re.fullmatch(pattern, name):
                raise RuntimeError('Unexpected live VINTF path: '+name)
            if path.parts[1] != 'apex' or '@' not in path.parts[2]:
                paths.append(name)
        paths = list(dict.fromkeys(paths))
        apex_count = sum(name.startswith('/apex/') for name in paths)-1
        if apex_count < 1:
            raise RuntimeError('No active unversioned APEX VINTF manifest was found')
        expected = remote_hashes(paths)
        for name in paths:
            value = call('exec-out', 'cat', name)
            if hashlib.sha256(value).hexdigest() != expected[name]:
                raise RuntimeError('Live input changed while being collected: '+name)
            if name == '/proc/config.gz':
                (output/'kernel.config.gz').write_bytes(value)
                (output/'kernel.config').write_bytes(gzip.decompress(value))
            else:
                destination = output/name.removeprefix('/')
                destination.parent.mkdir(parents=True, exist_ok=True)
                ET.fromstring(value)
                destination.write_bytes(value)
            receipt['inputs'][name] = expected[name]
        if remote_hashes(paths) != expected:
            raise RuntimeError('Live APEX/kernel inputs changed after collection')
        receipt['after'] = state()
        if receipt['after'] != receipt['before']:
            raise RuntimeError('Live baseline changed during collection')
        for part in partitions:
            (output/part).mkdir(exist_ok=True)
        tool = host/'checkvintf'
        tool_hash = hashlib.sha256(tool.read_bytes()).hexdigest()
        review_argv = [str(tool), '--check-compat']
        for part in (*partitions, 'apex'):
            review_argv += ['--dirmap', '/'+part+':'+str(output/part)]
        review_argv += ['--property', 'ro.product.first_api_level=34',
                        '--property', 'ro.boot.product.hardware.sku=sheng',
                        '--property', 'ro.boot.product.vendor.sku=kalama',
                        '--property', 'apex.all.ready=true',
                        '--kernel', '5.15.220:'+str(output/'kernel.config')]
        review = subprocess.run(review_argv, capture_output=True, timeout=55,
            env=dict(os.environ, LANG='C.UTF-8', LC_ALL='C.UTF-8',
                     LD_LIBRARY_PATH=str(host.parent/'lib64')))
        review_value = dict(argv=review_argv, returncode=review.returncode,
                           stdout=review.stdout.decode(errors='replace'),
                           stderr=review.stderr.decode(errors='replace'),
                           actual_live_partition_inputs=True, tool_sha256=tool_hash)
        (output/'vintf-review.json').write_text(json.dumps([review_value], indent=2)+'\n')
        review.check_returncode()
        if hashlib.sha256(tool.read_bytes()).hexdigest() != tool_hash:
            raise RuntimeError('VINTF validation tool changed during the check')
        receipt.update(passed=True, baseline_vintf_compatible=True,
                       kernel_config_sha256=hashlib.sha256((output/'kernel.config').read_bytes()).hexdigest(),
                       active_apex_vintf_files=apex_count,
                       validation_tool_sha256=tool_hash)
    except BaseException as error:
        receipt['error'] = repr(error)
        raise
    finally:
        (output/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
