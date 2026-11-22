#!/usr/bin/env python3
"""Sync finalized touch inputs after the recorded deferred-face isolation."""
import hashlib
import json
from pathlib import Path
import shutil
from prepare_sheng_touch_report_r50 import batch

workspace = Path('/mnt/c/Users/Dev裴月笙/Desktop/XiaomiPad6SProPort6.18')
rom = Path('/root/sheng-lineage/lineage-24.0')
work = Path('/root/sheng-lineage/hardware-diagnostics/sheng-touch-rate-r50-20261111')
assert (work/'build-inputs/source-sync.json').is_file()
assert not (rom/'device/xiaomi/sheng/sepolicy/system_ext/private/keystore2_key_contexts').exists()
target = rom/'device/xiaomi/sheng'
receipt = {}
for scope in batch.SCOPES:
    source = workspace/'device/xiaomi/sheng'/scope
    for path in sorted(source.rglob('*')) if source.is_dir() else [source]:
        if not path.is_file() or '__pycache__' in path.parts:
            continue
        relative = path.relative_to(workspace/'device/xiaomi/sheng')
        dest = target/relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        receipt[str(relative)] = hashlib.sha256(dest.read_bytes()).hexdigest()
for name in ['service.rc', 'manifest.xml']:
    stale = target/'interfaces/input/touch/hal'/name
    if stale.exists():
        assert stale.resolve().is_relative_to((target/'interfaces/input/touch/hal').resolve())
        stale.unlink()
old_log = work/'build.log'
if old_log.exists():
    assert not (work/'build-initial-interrupted.log').exists()
    shutil.move(old_log, work/'build-initial-interrupted.log')
(work/'final-source-sync.json').write_text(json.dumps(receipt, indent=2)+'\n')
