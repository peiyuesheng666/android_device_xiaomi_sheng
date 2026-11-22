#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Mirror the product app layout into the device-owned build tree with backups."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path

from audit_sheng_product_apps import audit


def digest(data): return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    checked = audit(source)
    rom = args.rom.resolve(strict=True)
    target = rom/'device/xiaomi/sheng'
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (rom/'out').mkdir(exist_ok=True)
    lock = (rom/'out/.sheng-device-modules.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), passed=False, normal_build_started=False, files={})

    def write(path, data, relative):
        assert path.resolve().is_relative_to(rom) and not path.is_symlink()
        before = path.read_bytes() if path.exists() else None
        if before != data:
            if before is not None:
                backup = output/'before'/relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(before)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        receipt['files'][relative] = dict(sha256=digest(data), changed=before != data,
                                          before_sha256=digest(before) if before is not None else None)

    try:
        selected = set(checked['source_sha256'])
        selected.update('tools/'+name for name in (
            'audit_sheng_product_apps.py', 'sync_sheng_product_apps.py', 'build_hardware.sh',
            'build_sheng_pen_ui.py', 'build_sheng_stylus_targeted.py', 'verify_sheng_stylus_modules.py',
            'build_sheng_pen_settings_product.sh', 'verify_sheng_dolby_apk.py',
            'package_sheng_product_apps.py', 'flash_sheng_product_apps.py',
            'verify_sheng_product_apps.py', 'package_sheng_pen_ui.py',
            'package_sheng_batch_helpers.py', 'verify_sheng_product_config.py'))
        selected.add('docs/PRODUCT_APPS.md')
        for relative in sorted(selected):
            write(target/relative, (source/relative).read_bytes(), 'device/xiaomi/sheng/'+relative)
        vendor = rom/'vendor/xiaomi/sheng'
        blueprint = vendor/'Android.bp'
        text = blueprint.read_text()
        marker = 'android_app_import {\n    name: "MiAONService",'
        assert text.count(marker) == 1
        start = text.index(marker)
        end = text.index('\n}\n', start)+3
        module = text[start:end]
        old_apk = 'proprietary/system_ext/app/MiAONService/MiAONService.apk'
        new_apk = 'proprietary/product/app/MiAONService/MiAONService.apk'
        if old_apk in module:
            assert module.count(old_apk) == 1 and module.count('system_ext_specific: true') == 1
            original = vendor/old_apk
            data = original.read_bytes()
            destination = vendor/new_apk
            assert not destination.exists() or destination.read_bytes() == data
            write(destination, data, 'vendor/xiaomi/sheng/'+new_apk)
            module = module.replace(old_apk, new_apk).replace('system_ext_specific: true', 'product_specific: true')
            write(blueprint, (text[:start]+module+text[end:]).encode(), 'vendor/xiaomi/sheng/Android.bp')
        else:
            assert new_apk in module and 'product_specific: true' in module
        assert audit(source) == checked
        mirrored = audit(target)
        assert mirrored == checked
        receipt.update(passed=True, application_count=checked['application_count'])
    except BaseException as error:
        receipt['error'] = repr(error)
        raise
    finally:
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        (output/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
        lock.close()
    print(json.dumps(dict(passed=True, application_count=receipt['application_count'], output=str(output))))


if __name__ == '__main__':
    main()
