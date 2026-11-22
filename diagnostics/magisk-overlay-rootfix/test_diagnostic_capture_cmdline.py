"""Capture opt-in parameter guards; these are not firmware/runtime tests."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'tools'))
from repack_sheng_boot_diagnostic_timeout import capture_cmdline

PARENT = 'console=null sheng_bootlog.enable=0 sheng_bootlog.test_timeout=0 sheng_bootlog.revision=legacy androidboot.foo=bar'


class CaptureCmdlineTests(unittest.TestCase):
    def test_explicit_opt_in_preserves_other_parameters(self):
        value = capture_cmdline(PARENT, timeout=45, revision='magisk-diag-20261121a')
        self.assertEqual(value, PARENT.replace('enable=0','enable=1').replace('timeout=0','timeout=45').replace('revision=legacy','revision=magisk-diag-20261121a'))

    def test_missing_duplicate_or_active_parent_rejected(self):
        for value in (PARENT.replace('sheng_bootlog.enable=0 ',''),
                      PARENT+' sheng_bootlog.enable=0',
                      PARENT+' sheng_bootlog.enable',
                      PARENT.replace('enable=0','enable=1'),
                      PARENT.replace('timeout=0','timeout=45'),
                      PARENT+' sheng_bootlog.test_timeout=0',
                      PARENT+' sheng_bootlog.revision=other'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                capture_cmdline(value, timeout=45, revision='fresh')

    def test_invalid_timeout_rejected(self):
        for timeout in (None,True,False,0,9,601,45.0,'45'):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                capture_cmdline(PARENT, timeout=timeout, revision='fresh')

    def test_invalid_or_reused_revision_rejected(self):
        for revision in (None,7,'','legacy','a'*65,'with space','bad=1','bad\n'):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                capture_cmdline(PARENT, timeout=45, revision=revision)

    def test_timeout_and_revision_limits(self):
        for timeout in (10,600):
            self.assertIn('test_timeout='+str(timeout), capture_cmdline(PARENT, timeout=timeout, revision='a'*64))

    def test_driver_isolation_not_silently_inherited(self):
        for flags in ('sheng_bootlog.pre_driver_hold_ms=1000', 'sheng_bootlog.pre_driver_hold_ms',
                      'sheng_bootlog.pre_driver_hold_ms=0 sheng_bootlog.pre_driver_hold_ms=0'):
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                capture_cmdline(PARENT+' '+flags,timeout=45,revision='fresh')
        self.assertIn('pre_driver_hold_ms=0',capture_cmdline(PARENT+' sheng_bootlog.pre_driver_hold_ms=0',timeout=45,revision='fresh'))


if __name__ == '__main__':
    unittest.main()
