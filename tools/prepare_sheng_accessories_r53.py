#!/usr/bin/env python3
"""Mirror accessory inputs only, preserving the installed deferred-face baseline."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

WORKSPACE = Path('/mnt/c/Users/Dev裴月笙/Desktop/XiaomiPad6SProPort6.18')
ROM = Path('/root/sheng-lineage/lineage-24.0')
WORK = Path('/root/sheng-lineage/hardware-diagnostics/sheng-accessories-r53-20261111')
SOURCE = WORKSPACE/'device/xiaomi/sheng'
TARGET = ROM/'device/xiaomi/sheng'
WORK.mkdir(exist_ok=True)
receipt = {}
for relative in [Path('BoardConfig.mk'), *sorted(Path('interfaces/input/keyboard')/p.relative_to(
        SOURCE/'interfaces/input/keyboard') for p in (SOURCE/'interfaces/input/keyboard').rglob('*')
        if p.is_file() and '.probe-build' not in p.parts)]:
    src, dst = SOURCE/relative, TARGET/relative
    if dst.exists():
        backup = WORK/'source-backup'/relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(dst, backup)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    receipt[str(relative)] = hashlib.sha256(dst.read_bytes()).hexdigest()

# device.mk has earlier native-face candidate edits in Windows. Preserve that
# work while adding this batch's identical footer to the installed WSL recipe.
footer = '\n# Permanent pogo endpoints need the actual attachment and cover-fold policy.\nPRODUCT_PACKAGES += ShengKeyboardPresence\n'
assert (SOURCE/'device.mk').read_text().endswith(footer)
recipe = TARGET/'device.mk'
text = recipe.read_text()
backup = WORK/'source-backup/device.mk'
if not backup.exists():
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(text)
if not text.endswith(footer):
    assert 'ShengKeyboardPresence' not in text
    recipe.write_text(text + footer)
assert recipe.read_text() == backup.read_text() + footer
face = TARGET/'sepolicy/system_ext/private/sheng_face.te'
keys = TARGET/'sepolicy/system_ext/private/keystore2_key_contexts'
if keys.exists():
    # The deferred namespace cannot be combined with the installed r44 mapping.
    # Preserve the candidate before selecting the same source baseline as r50.
    saved = WORK/'deferred-face-source'
    saved.mkdir(exist_ok=True)
    assert not (saved/keys.name).exists()
    shutil.copy2(face, saved/face.name)
    shutil.copy2(keys, saved/keys.name)
    face_text = face.read_text()
    start = face_text.index('# Hardware encryption keys have a dedicated SELinux namespace')
    end = face_text.index('allow sheng_face { app_api_service', start)
    face.write_text(face_text[:start] + face_text[end:])
    keys.unlink()
assert 'sheng_face_key' not in face.read_text()
assert not keys.exists()
receipt['device.mk'] = {'applied_footer': footer, 'preserved_installed_recipe_sha256':
    hashlib.sha256(backup.read_bytes()).hexdigest(), 'result_sha256': hashlib.sha256(recipe.read_bytes()).hexdigest()}
(WORK/'source-sync.json').write_text(json.dumps(receipt, indent=2)+'\n')
subprocess.run(['python3', SOURCE/'tools/verify_device_source_mirror.py', '--workspace', WORKSPACE,
    '--rom', ROM, '--path', 'BoardConfig.mk', '--path', 'interfaces/input/keyboard',
    '--output', WORK/'source-mirror.json'], check=True)
print('Accessory inputs mirrored; installed face and Dolby sources retained')
