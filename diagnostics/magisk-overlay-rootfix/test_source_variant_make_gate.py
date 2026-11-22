"""Real GNU Make gate tests on disposable copies, opt in with SHENG_VARIANTS_ROM.

Does not edit the ROM or public repositories. Not Soong/install acceptance.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('SHENG_VARIANTS_ROM'), 'Requires staged sheng ROM source')
class MakeGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sheng-variant-gate-', dir='/dev/shm')
        self.addCleanup(self.temp.cleanup)
        self.top = Path(self.temp.name)
        rom = Path(os.environ['SHENG_VARIANTS_ROM']).resolve(strict=True)
        device = rom / 'device/xiaomi/sheng'
        self.device = self.top / 'device/xiaomi/sheng'
        diagnostics = Path('diagnostics/magisk-overlay-rootfix')
        lock = json.loads((device / diagnostics / 'source-variants-lock.json').read_text())
        for relative in lock['sources']:
            source, target = rom / relative, self.top / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        for relative in ('interfaces/compat/first-stage-init', 'interfaces/compat/fs-mgr-first-stage',
                         'interfaces/compat/snapshot-first-stage', 'interfaces/compat/first-stage-crypto',
                         'interfaces/compat/first-stage-unwind', 'interfaces/compat/first-stage-zstd'):
            shutil.copytree(device / relative, self.device / relative)
        (self.device / diagnostics).mkdir(parents=True)
        for name in ('materialize_source_variants.py', 'storage_guard.py',
                     'source-variants-lock.json', 'fs_mgr-preserve-file-submounts.patch'):
            shutil.copy2(device / diagnostics / name, self.device / diagnostics / name)
        self.target = self.top / 'target.mk'
        self.target.write_text('all:\n\t@echo SHENG_GATE_TARGET_REACHED\n')

    def make(self, success, variant='userdebug', selected=True):
        command = ['make', '-s', '-f', str(self.device / 'interfaces/compat/first-stage-init/Android.mk'),
                   '-f', str(self.target), 'all', 'TARGET_DEVICE=sheng',
                   'TARGET_BUILD_VARIANT=' + variant,
                   'SOONG_CONFIG_sheng_first_stage_rootfix=' + ('true' if selected else 'false')]
        result = subprocess.run(command, cwd=self.top, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            self.assertIn(b'SHENG_GATE_TARGET_REACHED', result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'source verification failed', result.stderr)
            self.assertNotIn(b'SHENG_GATE_TARGET_REACHED', result.stdout)

    def test_valid_copies_pass(self):
        self.make(True)

    def test_modified_owned_source_stops_make(self):
        path = self.device / 'interfaces/compat/fs-mgr-first-stage/fs_mgr_overlayfs_mount.cpp'
        path.write_bytes(path.read_bytes() + b'\n// unexpected edit\n')
        self.make(False)

    def test_upstream_default_drift_stops_make(self):
        path = self.top / 'system/core/init/Android.bp'
        path.write_bytes(path.read_bytes() + b'\n// upstream drift\n')
        self.make(False)

    def test_patch_drift_stops_make(self):
        path = self.device / 'diagnostics/magisk-overlay-rootfix/fs_mgr-preserve-file-submounts.patch'
        path.write_bytes(path.read_bytes() + b'\n')
        self.make(False)

    def test_user_build_is_not_selected(self):
        path = self.device / 'interfaces/compat/fs-mgr-first-stage/fs_mgr_overlayfs_mount.cpp'
        path.write_bytes(b'invalid copy that is not selected on user builds')
        self.make(True, variant='user')

    def test_disabled_debug_fix_retains_public_sources(self):
        path = self.device / 'interfaces/compat/fs-mgr-first-stage/fs_mgr_overlayfs_mount.cpp'
        path.write_bytes(b'invalid owned copy must not be selected')
        self.make(True, selected=False)


if __name__ == '__main__':
    unittest.main()
