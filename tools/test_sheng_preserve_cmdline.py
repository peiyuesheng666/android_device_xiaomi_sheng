#!/usr/bin/env python3
"""Command-line policy only; not an AVB or device evidence-retention test."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('repack', Path(__file__).with_name(
    'repack_sheng_boot_diagnostic_timeout.py'))
repack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repack)


class PreserveTests(unittest.TestCase):
    def test_disables_writer_and_deadline(self):
        cmd = 'console=tty0 sheng_bootlog.enable=1 sheng_bootlog.test_timeout=180 sheng_bootlog.revision=r1'
        self.assertEqual(repack.preserve_cmdline(cmd),
            'console=tty0 sheng_bootlog.enable=0 sheng_bootlog.test_timeout=0 sheng_bootlog.revision=r1')

    def test_idempotent(self):
        cmd = 'sheng_bootlog.enable=0 sheng_bootlog.test_timeout=0'
        self.assertEqual(repack.preserve_cmdline(cmd), cmd)

    def test_rejects_ambiguous_or_invalid(self):
        for suffix in ('', ' sheng_bootlog.test_timeout', ' sheng_bootlog.test_timeout=-1',
                       ' sheng_bootlog.test_timeout=oops',
                       ' sheng_bootlog.test_timeout=0 sheng_bootlog.test_timeout=180'):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                repack.preserve_cmdline('sheng_bootlog.enable=1' + suffix)
        with self.assertRaises(ValueError):
            repack.preserve_cmdline('sheng_bootlog.enable=1 sheng_bootlog.enable=0 sheng_bootlog.test_timeout=0')


if __name__ == '__main__':
    unittest.main()
