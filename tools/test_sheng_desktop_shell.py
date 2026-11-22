#!/usr/bin/env python3
"""Verify a late policy conflict does not partially stage Shell fixes."""
import importlib.util
from pathlib import Path
import tempfile

spec = importlib.util.spec_from_file_location(
    'desktop_shell', Path(__file__).with_name('prepare_sheng_desktop_shell.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory(prefix='sheng-shell-preflight-') as folder:
    root = Path(folder)
    rom, patches = root / 'rom', root / 'patches'
    patches.mkdir()
    prefix = 'frameworks/base/libs/WindowManager/Shell/src/'
    for index, name in enumerate(('shell-policy.patch', 'display-mode-policy.patch',
                                  'home-transition.patch')):
        relative = prefix + f'Policy{index}.kt'
        target = rom / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('old\n')
        (patches / name).write_text(
            f'--- a/{relative}\n+++ b/{relative}\n@@ -1 +1 @@\n-old\n+new\n')
    # The keyboard upgrade overlaps an earlier policy and must preflight last.
    (patches / 'keyboard-auto-policy.patch').write_text(
        f'--- a/{prefix}Policy1.kt\n+++ b/{prefix}Policy1.kt\n@@ -1 +1 @@\n'
        '-new\n+keyboard-opt-in\n')
    conflict = rom / prefix / 'Policy2.kt'
    conflict.write_text('upstream-change\n')
    def snapshot():
        return {str(p.relative_to(rom)): p.read_bytes()
                for p in rom.rglob('*') if p.is_file()}
    before = snapshot()
    try:
        module.prepare_policies(rom, patches)
    except AssertionError:
        pass
    else:
        raise AssertionError('Conflicting final policy was accepted')
    assert snapshot() == before, 'Preflight left a partial policy set'
    conflict.write_text('old\n')
    result = module.prepare_policies(rom, patches)
    assert result['state'] == 'applied'
    assert (rom / prefix / 'Policy1.kt').read_text() == 'keyboard-opt-in\n'
    before = snapshot()
    result = module.prepare_policies(rom, patches)
    assert result['state'] == 'already_applied' and snapshot() == before
print('PASS: late policy conflict preserves all sources; complete staging is repeatable')
