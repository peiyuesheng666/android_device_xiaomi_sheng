#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read the effective product app configuration without loading a build graph."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

from audit_sheng_product_apps import audit


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def graph_state(rom):
    paths = list((rom/'out').glob('*.ninja')) + list((rom/'out/soong').glob('*.ninja'))
    return {str(path.relative_to(rom)): [path.stat().st_size, path.stat().st_mtime_ns]
            for path in sorted(paths)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument('--product', choices=('lineage_sheng', 'custom_sheng'))
    parser.add_argument('--release', default='cp2a')
    parser.add_argument('--variant', choices=('user', 'userdebug', 'eng'), default='userdebug')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    rom = args.rom.resolve(strict=True)
    product = args.product or ('custom_sheng' if (rom/'vendor/custom/config/common_full_tablet_wifionly.mk').is_file()
                               else 'lineage_sheng')
    device = rom/'device/xiaomi/sheng'
    checked = audit(source)
    assert audit(device) == checked, 'Product layout source mirror differs'
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    receipt = dict(started_utc=datetime.now(timezone.utc).isoformat(), passed=False,
                   scope='effective Make product configuration', normal_module_build_started=False,
                   full_product_build_started=False, ninja_graph_loaded=False,
                   source_sha256=checked['source_sha256'])
    (rom/'out').mkdir(exist_ok=True)
    with (rom/'out/.sheng-device-modules.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            before = graph_state(rom)
            receipt['active_swap_devices'] = Path('/proc/swaps').read_text().splitlines()[1:]
            for line in receipt['active_swap_devices']:
                swap = Path(line.split()[0]).resolve()
                assert not str(swap).lower().startswith('/mnt/e/'), 'E-drive swap is prohibited'
            variables = ['TARGET_PRODUCT', 'PRODUCT_NAME', 'PRODUCT_DEVICE',
                         'PRODUCT_SHIPPING_API_LEVEL', 'PRODUCT_ENFORCE_PRODUCT_PARTITION_INTERFACE',
                         'TARGET_COPY_OUT_PRODUCT', 'TARGET_COPY_OUT_SYSTEM_EXT',
                         'PRODUCT_PACKAGES', 'PRODUCT_COPY_FILES']
            command = ['build/soong/soong_ui.bash', '--dumpvars-mode', '--vars='+' '.join(variables)]
            env = dict(os.environ)
            for key in ('PRODUCT_ENFORCE_PRODUCT_PARTITION_INTERFACE',
                        'OVERRIDE_PRODUCT_ENFORCE_PRODUCT_PARTITION_INTERFACE',
                        'PRODUCT_SHIPPING_API_LEVEL', 'WRITE_SOONG_VARIABLES',
                        'CALLED_FROM_SETUP', 'CALLED_PRE_PRODUCT_CONFIG'):
                env.pop(key, None)
            env.update(TARGET_PRODUCT=product, TARGET_RELEASE=args.release,
                       TARGET_BUILD_VARIANT=args.variant, TARGET_BUILD_TYPE='release', OUT_DIR='out',
                       LANG='C.UTF-8', LC_ALL='C.UTF-8', TZ='Asia/Singapore',
                       GOMEMLIMIT='2GiB', GOGC='50', GOMAXPROCS='2', SOONG_NINJA='ninja')
            receipt['command'] = command
            native = rom.parent/'hardware-diagnostics'
            native.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='product-config-', dir=native) as scratch:
                env['TMPDIR'] = scratch
                result = subprocess.run(command, cwd=rom, env=env, text=True,
                                        capture_output=True, timeout=240)
            (output/'dumpvars.stdout').write_text(result.stdout)
            (output/'dumpvars.stderr').write_text(result.stderr)
            receipt['exit_code'] = result.returncode
            result.check_returncode()
            values = {}
            for line in result.stdout.splitlines():
                match = re.fullmatch(r'([A-Z_0-9]+)=(.*)', line)
                if match and match[1] in variables:
                    parsed = shlex.split(match[2])
                    assert len(parsed) == 1
                    values[match[1]] = parsed[0]
            receipt['effective_values'] = values
            expected = dict(TARGET_PRODUCT=product, PRODUCT_NAME=product,
                            PRODUCT_DEVICE='sheng', PRODUCT_SHIPPING_API_LEVEL='34',
                            PRODUCT_ENFORCE_PRODUCT_PARTITION_INTERFACE='false',
                            TARGET_COPY_OUT_PRODUCT='product', TARGET_COPY_OUT_SYSTEM_EXT='system_ext')
            for key, value in expected.items():
                assert values.get(key) == value, (key, values.get(key), value)
            catalog = json.loads((source/'configs/product-apps.json').read_text())
            installed = set(values['PRODUCT_PACKAGES'].split())
            assert {app['module'] for app in catalog['applications']} <= installed
            assert not {app['module'] for app in catalog['uninstalled_applications']} & installed
            copy = ('device/xiaomi/sheng/interfaces/location/permissions/default-permissions-sheng-location.xml'
                    ':product/etc/default-permissions/default-permissions-sheng-location.xml')
            assert copy in values['PRODUCT_COPY_FILES'].split()
            assert before == graph_state(rom), 'A generated build graph changed during configuration inspection'
            assert audit(source) == checked and audit(device) == checked
            receipt['build_source_sha256'] = {relative: sha(rom/relative) for relative in (
                'build/make/core/product_config.mk', 'build/make/core/product.mk',
                'build/make/core/soong_config.mk', 'build/soong/ui/build/dumpvars.go',
                'build/soong/android/module.go', 'build/soong/java/base.go')}
            receipt.update(passed=True, application_count=len(catalog['applications']),
                           generated_graphs_unchanged=True)
        except BaseException as error:
            receipt['error'] = repr(error)
            raise
        finally:
            receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
            (output/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(dict(passed=True, application_count=receipt['application_count'],
                         normal_module_build_started=False, output=str(output))))


if __name__ == '__main__':
    main()
