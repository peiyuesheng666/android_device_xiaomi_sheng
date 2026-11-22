import lzma
from pathlib import Path
import stat
import tempfile
import unittest

from package_source_boot_family import (inventory, init_replacement, module_replacements,
                                      parse_cpio, replace_records, validate_bootlog_policy,
                                      preserve_rawdump_cmdline, kernel_arguments)
from build_sheng_fastbootd_cold_trace import new_entry
from test_source_binary_export import elf


def cpio(files):
    records = b''.join(new_entry(name, data, mode, i + 1) for i, (name, data, mode) in enumerate(files))
    records += new_entry('TRAILER!!!', b'', 0, len(files) + 1)
    return records + bytes(-len(records) % 512)


class BootFamilyTests(unittest.TestCase):
    def test_release_pystore_requires_new_linked_audit_not_diagnostic_receipt(self):
        config = 'CONFIG_SHENG_BOOTLOG=y\nCONFIG_LOG_BUF_SHIFT=22\n'
        audit = dict(bootlog_disabled=False, diagnostic_only=False,
                     logger_identity_verified_in_object_and_vmlinux=True,
                     pystore_boot_only_verified_in_object_and_vmlinux=True)
        validate_bootlog_policy(config, audit, release_pystore=True)
        for key in audit:
            broken = dict(audit)
            del broken[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_bootlog_policy(config, broken, release_pystore=True)
        with self.assertRaises(ValueError):
            validate_bootlog_policy(config, dict(audit, diagnostic_only=True), release_pystore=True)
        with self.assertRaises(ValueError):
            validate_bootlog_policy(config, audit, diagnostic=True, release_pystore=True)

    def test_release_records_boot_preserves_recovery_without_test_holds(self):
        before = ['--kernel', '/old/kernel', '--cmdline',
                  'console=null sheng_bootlog.enable=0 sheng_bootlog.test_timeout=180 '
                  'sheng_bootlog.pre_driver_hold_ms=4000 sheng_bootlog.boot_complete=1']
        for name in ('boot', 'recovery'):
            after, changed = kernel_arguments(name, before, '/new/kernel', release_pystore=True,
                                               recovery_embeds_kernel=True)
            self.assertTrue(changed)
            self.assertEqual(after[3], 'console=null sheng_bootlog.enable=' +
                             ('1' if name == 'boot' else '0') + ' sheng_bootlog.test_timeout=0')
        self.assertEqual(kernel_arguments('vendor_boot', before, '/new', release_pystore=True),
                         (before, False))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.stage = Path(self.temp.name)
        (self.stage / 'a.ko').write_bytes(b'new module')
        (self.stage / 'modules.load').write_bytes(b'a.ko\n')
        (self.stage / 'modules.load.recovery').write_bytes(b'# recovery\na.ko\n')
        self.plain = cpio([('lib/modules/a.ko', b'old module', stat.S_IFREG | 0o644),
                           ('lib/modules/modules.load', b'a\n', stat.S_IFREG | 0o644),
                           ('keep', b'unrelated bytes', stat.S_IFREG | 0o600)])

    def test_modules_metadata_and_unrelated_records(self):
        replacements = module_replacements(self.plain, self.stage)
        after = inventory(replace_records(self.plain, replacements, parse_cpio))
        before = inventory(self.plain)
        self.assertEqual(after['keep']['raw'], before['keep']['raw'])
        self.assertEqual(after['lib/modules/a.ko']['payload'], b'new module')
        self.assertEqual(after['lib/modules/a.ko']['fields'][1:6], before['lib/modules/a.ko']['fields'][1:6])
        self.assertEqual(after['lib/modules/modules.load']['payload'], b'a.ko\n')

    def test_recovery_uses_recovery_load_sequence(self):
        self.assertEqual(module_replacements(self.plain, self.stage, recovery=True)['lib/modules/modules.load'], b'# recovery\na.ko\n')

    def test_added_or_missing_module_rejected(self):
        (self.stage / 'extra.ko').write_bytes(b'no')
        with self.assertRaises(ValueError):
            module_replacements(self.plain, self.stage)
        (self.stage / 'extra.ko').unlink()
        (self.stage / 'a.ko').unlink()
        with self.assertRaises(ValueError):
            module_replacements(self.plain, self.stage)

    def test_unknown_metadata_and_symlink_rejected(self):
        unknown = cpio([('lib/modules/a.ko', b'old', stat.S_IFREG | 0o644),
                        ('lib/modules/modules.dep.bin', b'unknown', stat.S_IFREG | 0o644)])
        with self.assertRaises(ValueError):
            module_replacements(unknown, self.stage)
        linked = cpio([('lib/modules/a.ko', b'target', stat.S_IFLNK | 0o777)])
        with self.assertRaises(ValueError):
            module_replacements(linked, self.stage)

    def test_init_backup_only_magisk_unchanged(self):
        original = cpio([('.backup/init.xz', lzma.compress(elf()), stat.S_IFREG | 0o750),
                         ('init', b'preserved Magisk payload', stat.S_IFREG | 0o750)])
        new_init = elf() + b'new executable'
        replacements = init_replacement(original, new_init)
        after = inventory(replace_records(original, replacements, parse_cpio))
        self.assertEqual(after['init']['raw'], inventory(original)['init']['raw'])
        self.assertEqual(lzma.decompress(after['.backup/init.xz']['payload']), new_init)

    def test_unknown_backup_or_non_arm64_refused(self):
        with self.assertRaises(ValueError):
            init_replacement(self.plain, elf())
        broken = cpio([('.backup/init.xz', lzma.compress(b'not init'), stat.S_IFREG | 0o750)])
        with self.assertRaises(ValueError):
            init_replacement(broken, elf())

    def test_release_rejects_enabled_logger_even_with_claimed_release_receipt(self):
        validate_bootlog_policy('# CONFIG_SHENG_BOOTLOG is not set\n', {'bootlog_disabled': True})
        for audit in ({'bootlog_disabled': True}, {'bootlog_disabled': False}):
            with self.assertRaises(ValueError):
                validate_bootlog_policy('CONFIG_SHENG_BOOTLOG=y\n', audit)

    def test_diagnostic_requires_actual_config_and_linked_qualification(self):
        config = 'CONFIG_SHENG_BOOTLOG=y\nCONFIG_LOG_BUF_SHIFT=22\n'
        audit = dict(bootlog_disabled=False, diagnostic_only=True,
                     logger_identity_verified_in_object_and_vmlinux=True)
        validate_bootlog_policy(config, audit, diagnostic=True)
        for key in audit:
            broken = dict(audit)
            del broken[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                validate_bootlog_policy(config, broken, diagnostic=True)
        for broken in ('# CONFIG_SHENG_BOOTLOG is not set\n',
                       config.replace('SHIFT=22', 'SHIFT=17'),
                       config+'# CONFIG_SHENG_BOOTLOG is not set\n', ''):
            with self.assertRaises(ValueError):
                validate_bootlog_policy(broken, audit, diagnostic=True)

    def test_preserve_cmdline_disables_writer_and_reset_without_changing_other_flags(self):
        before = 'console=null sheng_bootlog.enable=1 sheng_bootlog.test_timeout=45 panic=5'
        after = preserve_rawdump_cmdline(before)
        self.assertEqual(after, 'console=null sheng_bootlog.enable=0 sheng_bootlog.test_timeout=0 panic=5')
        self.assertEqual(preserve_rawdump_cmdline(after), after)
        self.assertEqual(preserve_rawdump_cmdline('console=null'), 'console=null sheng_bootlog.enable=0')
        self.assertEqual(preserve_rawdump_cmdline(''), 'sheng_bootlog.enable=0')

    def test_ambiguous_cmdline_rejected(self):
        for value in ('sheng_bootlog.enable=1 sheng_bootlog.enable=0',
                      'sheng_bootlog.test_timeout=0 sheng_bootlog.test_timeout=45'):
            with self.assertRaises(ValueError):
                preserve_rawdump_cmdline(value)

    def test_both_boot_and_recovery_replace_kernel_and_disable_recorder(self):
        before = ['--kernel', '/old/kernel', '--cmdline', 'console=null sheng_bootlog.enable=1',
                  '--dtb', '/parent/dtb', '--header_version', '4']
        for name in ('boot', 'recovery'):
            with self.subTest(name=name):
                after, changed = kernel_arguments(name, before, Path('/qualified/kernel'), diagnostic=True,
                                                  recovery_embeds_kernel=True)
                self.assertEqual(after[1], '/qualified/kernel')
                self.assertEqual(after[3], 'console=null sheng_bootlog.enable=0')
                self.assertEqual(after[4:], before[4:])
                self.assertTrue(changed)
                self.assertEqual(before[1], '/old/kernel')
        self.assertEqual(kernel_arguments('init_boot', before, '/new', diagnostic=True), (before, False))

    def test_missing_recovery_kernel_or_duplicate_cmdline_rejected(self):
        with self.assertRaises(ValueError):
            kernel_arguments('recovery', ['--ramdisk', '/old/ramdisk'], '/new')
        with self.assertRaises(ValueError):
            kernel_arguments('boot', ['--kernel', '/old', '--cmdline', '', '--cmdline', ''], '/new', diagnostic=True)

    def test_shared_kernel_recovery_keeps_empty_payload_and_disables_recorder(self):
        before = ['--kernel', '/unpacked/empty-kernel', '--ramdisk', '/parent/ramdisk', '--cmdline', 'console=null']
        after, changed = kernel_arguments('recovery', before, '/qualified/kernel', diagnostic=True,
                                          recovery_embeds_kernel=False)
        self.assertEqual(after[1:4], before[1:4])
        self.assertEqual(after[-1], 'console=null sheng_bootlog.enable=0')
        self.assertTrue(changed)
        with self.assertRaises(ValueError):
            kernel_arguments('recovery', before, '/qualified/kernel')


class PreserveReleaseTests(unittest.TestCase):
    def test_preserve_disables_both_and_strips_hold_and_timeout(self):
        before = ['--kernel', '/old', '--cmdline',
                  'console=null sheng_bootlog.enable=1 sheng_bootlog.test_timeout=180 '
                  'sheng_bootlog.pre_driver_hold_ms=4000 sheng_bootlog.boot_complete=1']
        for name in ('boot', 'recovery'):
            after, _ = kernel_arguments(name, before, '/new', preserve_rawdump=True,
                                         recovery_embeds_kernel=True)
            self.assertEqual(after[-1], 'console=null sheng_bootlog.enable=0 sheng_bootlog.test_timeout=0')


if __name__ == '__main__':
    unittest.main()
