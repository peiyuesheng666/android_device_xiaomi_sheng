#!/usr/bin/env python3
"""Exercise Recovery source reconciliation against incomplete build mirrors."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1]
PREPARE = SOURCE / 'tools/prepare_sheng_pen_settings_product.py'
MARKER = '# Recovery starts the optional oops logger after storage coldboot.'
BLOCK = (SOURCE / 'device.mk').read_text().split(MARKER, 1)[1].split('\n\n', 1)[0]
BLOCK = MARKER + BLOCK
OLD_BLOCK = '\n'.join(line for line in BLOCK.splitlines()
                      if '/rootdir/recovery/hardware.sh:' not in line)
TOUCH_MARKER = '# Recovery touch processing uses the same stock inputs as accepted r59.'
TOUCH_BLOCK = TOUCH_MARKER + (SOURCE / 'device.mk').read_text().split(TOUCH_MARKER, 1)[1].split('\n\n', 1)[0]
PRESERVED = '# unrelated product input\nPRODUCT_PACKAGES += retained_keyboard\n'


class RecoverySourceSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sheng-recovery-sync-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rom = self.root / 'rom'
        self.target = self.rom / 'device/xiaomi/sheng'
        self.target.mkdir(parents=True)
        (self.target / 'BoardConfig.mk').write_text(
            'TARGET_RECOVERY_PIXEL_FORMAT := RGBX_8888\n# unrelated board input\n'
            'BOOT_KERNEL_MODULES := $(strip $(shell cat $(DEVICE_PATH)/configs/modules/modules.list.recovery))\n')
        self.product = self.target / 'device.mk'
        self.product.write_text(PRESERVED + '\n' + OLD_BLOCK + '\n')

    def prepare(self, name, *, succeeds=True):
        work = self.root / name
        result = subprocess.run([sys.executable, str(PREPARE), '--rom', str(self.rom),
                                 '--work', str(work), '--include-recovery'],
                                text=True, capture_output=True)
        if succeeds:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads((work / 'source-sync.json').read_text())
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_restore_complete_recovery_inputs_and_preserve_prior_sources(self):
        stale = self.target / 'sepolicy/vendor/init.te'
        stale.parent.mkdir(parents=True)
        stale.write_bytes(b'old recovery policy\n')
        receipt = self.prepare('first')
        files = [path.relative_to(SOURCE) for path in (SOURCE / 'rootdir/recovery').rglob('*')
                 if path.is_file()]
        files += [Path(name) for name in (
            'rootdir/etc/init.recovery.qcom.rc', 'sepolicy/vendor/file.te',
            'sepolicy/vendor/init.te', 'sepolicy/vendor/genfs_contexts')]
        for relative in files:
            self.assertEqual((self.target / relative).read_bytes(), (SOURCE / relative).read_bytes())
        self.assertEqual((self.root / 'first/source-backup/sepolicy/vendor/init.te').read_bytes(),
                         b'old recovery policy\n')
        self.assertIn(PRESERVED, self.product.read_text())
        self.assertIn(BLOCK, self.product.read_text())
        self.assertIn(TOUCH_BLOCK, self.product.read_text())
        self.assertEqual(self.product.read_text().count(':recovery/root/system/bin/sheng-recovery-hardware'), 1)
        self.assertIn('# unrelated board input', (self.target / 'BoardConfig.mk').read_text())
        self.assertIn('BOOT_KERNEL_MODULES := $(sort $(shell cat $(DEVICE_PATH)/configs/modules/modules.list.boot ',
                      (self.target / 'BoardConfig.mk').read_text())
        self.assertTrue(receipt['declarations']['device.mk']['other_product_lines_preserved'])
        second = self.prepare('second')
        self.assertTrue(all(not value['changed'] for value in second['files'].values()))

    def test_upgrade_crlf_product_without_changing_other_lines(self):
        self.product.write_bytes((PRESERVED + '\n' + OLD_BLOCK + '\n').replace('\n', '\r\n').encode())
        self.prepare('crlf')
        data = self.product.read_bytes()
        self.assertIn(PRESERVED.replace('\n', '\r\n').encode(), data)
        self.assertIn(BLOCK.replace('\n', '\r\n').encode(), data)
        self.assertNotIn(b'\n', data.replace(b'\r\n', b''))

    def test_reject_unrecognized_copy_block_without_changing_product(self):
        before = (PRESERVED + '\n' + OLD_BLOCK.replace('late-modules.sh:', 'local-modules.sh:') + '\n').encode()
        self.product.write_bytes(before)
        result = self.prepare('conflict', succeeds=False)
        self.assertIn('Review the existing Recovery copy block', result.stderr)
        self.assertEqual(self.product.read_bytes(), before)
        self.assertFalse((self.target / 'rootdir').exists())

    def test_reject_duplicate_hardware_install_destination(self):
        before = self.product.read_bytes() + b'\nPRODUCT_COPY_FILES += local.sh:recovery/root/system/bin/sheng-recovery-hardware\n'
        self.product.write_bytes(before)
        result = self.prepare('duplicate', succeeds=False)
        self.assertIn('Review duplicate Recovery hardware destination', result.stderr)
        self.assertEqual(self.product.read_bytes(), before)

    def test_reject_unrecognized_touch_copy_block(self):
        before = (PRESERVED + '\n' + BLOCK + '\n\n' + TOUCH_BLOCK.replace(
            'film_model.tflite', 'unreviewed_model.tflite') + '\n').encode()
        self.product.write_bytes(before)
        result = self.prepare('touch-conflict', succeeds=False)
        self.assertIn('Review the existing Recovery touch block', result.stderr)
        self.assertEqual(self.product.read_bytes(), before)

    def test_reject_separately_registered_touch_runtime(self):
        before = self.product.read_bytes() + b'\nPRODUCT_PACKAGES += sheng-recovery-touch-runtime\n'
        self.product.write_bytes(before)
        result = self.prepare('touch-duplicate', succeeds=False)
        self.assertIn('Review duplicate Recovery touch registration', result.stderr)
        self.assertEqual(self.product.read_bytes(), before)

    def test_preserve_unknown_boot_module_assignment(self):
        board = self.target / 'BoardConfig.mk'
        before = board.read_text().replace('$(strip $(shell cat', '$(custom $(shell cat').encode()
        board.write_bytes(before)
        result = self.prepare('boot-conflict', succeeds=False)
        self.assertIn('Review the existing boot module packaging assignment', result.stderr)
        self.assertEqual(board.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
