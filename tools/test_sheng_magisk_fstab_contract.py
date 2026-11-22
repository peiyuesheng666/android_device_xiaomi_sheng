#!/usr/bin/env python3
"""Reject overlay opt-outs and loss of AVB in either /system alternative."""
from pathlib import Path
import tempfile
import unittest

from test_sheng_magisk_overlay_handoff import check_fstab


class FstabContractTest(unittest.TestCase):
    def check(self, rows):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'fstab.qcom'
            path.write_text(rows)
            return check_fstab(path)

    def rows(self, flags='wait,slotselect,avb=vbmeta_system,logical,first_stage_mount'):
        return ''.join(f'system /system {fs} ro {flags}\n' for fs in ('erofs', 'ext4'))

    def test_both_alternatives(self):
        self.assertTrue(self.check(self.rows())['all_system_first_stage_alternatives_allow_normal_overlay'])

    def test_overlay_off_is_not_a_root_fix(self):
        with self.assertRaises(AssertionError):
            self.check(self.rows('wait,slotselect,avb=vbmeta_system,logical,first_stage_mount,overlay=off'))

    def test_missing_filesystem_alternative(self):
        with self.assertRaises(AssertionError):
            self.check(self.rows().splitlines()[0] + '\n')

    def test_forced_overlay_on_rejected(self):
        with self.assertRaises(AssertionError):
            self.check(self.rows('wait,slotselect,avb=vbmeta_system,logical,first_stage_mount,overlay=on'))

    def test_avb_cannot_be_removed(self):
        with self.assertRaises(AssertionError):
            self.check(self.rows('wait,slotselect,logical,first_stage_mount'))

    def test_one_alternative_opt_out_rejected(self):
        rows=self.rows().splitlines()
        rows[1]+=',overlay=off'
        with self.assertRaises(AssertionError):
            self.check('\n'.join(rows)+'\n')

    def test_checked_in_fstab(self):
        result=check_fstab(Path(__file__).resolve().parents[1]/'rootdir/etc/fstab.qcom')
        self.assertTrue(result['system_avb_flags_retained'])


if __name__ == '__main__':
    unittest.main()
