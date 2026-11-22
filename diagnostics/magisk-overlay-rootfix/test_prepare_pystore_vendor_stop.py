from pathlib import Path
import tempfile
import unittest
from prepare_pystore_vendor_stop import source_delta


class SourceDeltaTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.device=Path(self.temp.name)
        contents={
            'sepolicy/vendor/file.te':'type vendor_sysfs_sheng_boot_complete, fs_type, sysfs_type;\n',
            'sepolicy/vendor/vendor_init.te':'allow vendor_init vendor_sysfs_sheng_boot_complete:file { open write getattr };\n',
            'sepolicy/vendor/genfs_contexts':'genfscon sysfs /module/sheng_bootlog/parameters/boot_complete u:object_r:vendor_sysfs_sheng_boot_complete:s0\n',
            'rootdir/etc/init.sheng.rc':'on property:sys.boot_completed=1\n    write /sys/module/sheng_bootlog/parameters/boot_complete 1\n',
        }
        for name,text in contents.items():
            path=self.device/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)

    def test_exact_scoped_rules_and_versioned_vendor_init(self):
        rc,cil,_=source_delta(self.device,'202604')
        self.assertIn('boot_complete 1\n',rc)
        self.assertIn('(allow vendor_init_202604 vendor_sysfs_sheng_boot_complete (file (getattr open write)))',cil)
        self.assertEqual(len(cil.splitlines()),6)
        self.assertNotIn('(allow domain ',cil)

    def test_rejects_missing_or_modified_source_rule(self):
        path=self.device/'sepolicy/vendor/vendor_init.te'
        path.write_text(path.read_text().replace('open write getattr','open read write getattr'))
        with self.assertRaises(AssertionError):source_delta(self.device,'202604')

    def test_rejects_duplicate_type_and_wrong_stop_value(self):
        path=self.device/'sepolicy/vendor/file.te';old=path.read_text();path.write_text(old*2)
        with self.assertRaises(AssertionError):source_delta(self.device,'202604')
        path.write_text(old)
        rc=self.device/'rootdir/etc/init.sheng.rc';rc.write_text(rc.read_text().replace('boot_complete 1','boot_complete 0'))
        with self.assertRaises(AssertionError):source_delta(self.device,'202604')

    def test_rejects_invalid_mapping_version(self):
        with self.assertRaises(AssertionError):source_delta(self.device,'202604) bad-rule')


if __name__=='__main__':unittest.main()
