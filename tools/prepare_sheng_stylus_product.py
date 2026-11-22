#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Mirror stylus sources and explicit device policy, matrix and package declarations."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

SOURCE = Path(__file__).resolve().parents[1]
ROM = Path('/root/sheng-lineage/lineage-24.0')
TARGET = ROM/'device/xiaomi/sheng'
work = Path(sys.argv[1]).resolve(strict=True)
receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), files={},
               public_sources_changed=False, product_packages_enabled=False, installed=False)
sha = lambda data: hashlib.sha256(data).hexdigest()

def write(relative, data):
    target = TARGET/relative
    before = target.read_bytes() if target.exists() else None
    if before != data:
        backup = work/'stylus-source-backup'/relative
        if before is not None:
            backup.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists(): raise RuntimeError('Backup would be overwritten: '+str(backup))
            backup.write_bytes(before)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    receipt['files'][str(relative)] = dict(before_sha256=sha(before) if before is not None else None,
                                         sha256=sha(data), changed=before != data)

if not TARGET.is_dir() or SOURCE.resolve() == TARGET.resolve():
    raise RuntimeError('Expected separate source and ROM device mirrors')
package_line = 'PRODUCT_PACKAGES += ShengStylus vendor.lineage.sheng.stylus-service'
packages_enabled = package_line in (SOURCE/'device.mk').read_text().splitlines()
if packages_enabled:
    api = SOURCE/'interfaces/input/stylus'
    if not re.search(r'\bfrozen:\s*true\s*,', (api/'Android.bp').read_text()):
        raise RuntimeError('Product inclusion requires the frozen control interface')
    if not re.fullmatch(r'[0-9a-f]{40}', (api/'aidl_api/vendor.lineage.sheng.stylus/1/.hash').read_text().strip()):
        raise RuntimeError('Frozen V1 API hash is missing or invalid')
receipt['product_packages_enabled'] = packages_enabled
stylus = Path('interfaces/input/stylus')
for path in sorted((SOURCE/stylus).rglob('*')):
    if path.is_file():
        write(path.relative_to(SOURCE), path.read_bytes())
        shutil.copymode(path, TARGET/path.relative_to(SOURCE))
matrix = Path('configs/vintf/framework_stylus_matrix.xml')
write(matrix, (SOURCE/matrix).read_bytes())
board = (TARGET/'BoardConfig.mk').read_text()
lines = [
    'SYSTEM_EXT_PUBLIC_SEPOLICY_DIRS += $(DEVICE_PATH)/interfaces/input/stylus/sepolicy/system_ext/public',
    'SYSTEM_EXT_PRIVATE_SEPOLICY_DIRS += $(DEVICE_PATH)/interfaces/input/stylus/sepolicy/system_ext/private',
    'BOARD_VENDOR_SEPOLICY_DIRS += $(DEVICE_PATH)/interfaces/input/stylus/sepolicy/vendor']
for line in lines:
    if line not in (SOURCE/'BoardConfig.mk').read_text().splitlines():
        raise RuntimeError('Source board declaration missing: '+line)
    if line not in board.splitlines(): board = board.rstrip()+'\n'+line+'\n'
if '$(DEVICE_PATH)/configs/vintf/framework_stylus_matrix.xml' not in board:
    board = board.rstrip()+'\nDEVICE_FRAMEWORK_COMPATIBILITY_MATRIX_FILE += $(DEVICE_PATH)/configs/vintf/framework_stylus_matrix.xml\n'
write(Path('BoardConfig.mk'), board.encode('utf-8'))
if packages_enabled:
    product = (TARGET/'device.mk').read_text()
    if package_line not in product.splitlines():
        if re.search(r'\bShengStylus\b|\bvendor\.lineage\.sheng\.stylus-service\b', product):
            raise RuntimeError('Review the existing stylus product declarations')
        product = product.rstrip()+'\n\n# Persistent pen transport with the frozen vendor control interface.\n'+package_line+'\n'
    write(Path('device.mk'), product.encode('utf-8'))
(work/'stylus-source-sync.json').write_text(json.dumps(receipt, indent=2)+'\n')
print(json.dumps(dict(files=len(receipt['files']), installed=False,
                      product_packages_enabled=packages_enabled)))
