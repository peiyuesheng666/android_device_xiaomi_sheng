#!/usr/bin/env python3
"""Exercise the device's real Make expansion; no kernel/device acceptance."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
BOARD = ROOT / 'device/xiaomi/sheng/interfaces/kernel/6.18/BoardConfig.mk'


class RecoveryArgumentsTest(unittest.TestCase):
    def test_recovery_override_retains_normal_args_and_pack_flags(self):
        with tempfile.TemporaryDirectory(prefix='sheng-rec-args-') as name:
            temp = Path(name)
            capture = temp / 'capture.py'
            capture.write_text('import json,sys; print(json.dumps(sys.argv[1:]))\n')
            makefile = temp / 'Makefile'
            makefile.write_text('DEVICE_PATH := device/xiaomi/sheng\n'
                                'BOARD_MKBOOTIMG_ARGS := --header_version 4 --os_version 17\n'
                                'INTERNAL_KERNEL_CMDLINE := console=null bootconfig\n'
                                f'include {BOARD}\n'
                                f'all:\n\t@python3 {capture} --normal "$(INTERNAL_KERNEL_CMDLINE)" '
                                '$(BOARD_RECOVERY_MKBOOTIMG_ARGS)\n')
            out = subprocess.check_output(['make', '--no-print-directory', '-f', str(makefile), 'all'],
                                          cwd=ROOT, text=True)
            args = json.loads(out)
            self.assertEqual(args[:2], ['--normal', 'console=null bootconfig'])
            self.assertEqual(args[2:6], ['--header_version', '4', '--os_version', '17'])
            self.assertEqual(args[6:], ['--cmdline', 'console=null bootconfig '
                                       'sheng_bootlog.enable=0 sheng_bootlog.test_timeout=0'])


if __name__ == '__main__':
    unittest.main()
