"""Regression checks for the sheng KSU modversions audit."""
import struct
import unittest

from audit_sheng_ksu_source_module import version_crcs


def tables(names, *, basic_crc=7, extended_crc=7):
    return {
        '__versions': (None, struct.pack('<Q56s', basic_crc, b'module_layout')),
        '__version_ext_crcs': (None, struct.pack('<I', extended_crc)),
        '__version_ext_names': (None, names),
    }


class VersionCrcTests(unittest.TestCase):
    def test_identical_sections_with_trailing_zero(self):
        self.assertEqual(version_crcs(tables(b'module_layout\0\0')), {'module_layout': 7})

    def test_rejects_extra_and_empty_names(self):
        for names in (b'module_layout\0extra\0', b'\0module_layout\0', b'module_layout'):
            with self.subTest(names=names), self.assertRaises(ValueError):
                version_crcs(tables(names))

    def test_tables_must_agree(self):
        with self.assertRaisesRegex(ValueError, 'tables disagree'):
            version_crcs(tables(b'module_layout\0', extended_crc=8))

    def test_basic_and_extended_independently_supported(self):
        both = tables(b'module_layout\0')
        for keys in (('__versions',), ('__version_ext_crcs', '__version_ext_names')):
            with self.subTest(keys=keys):
                self.assertEqual(version_crcs({k: both[k] for k in keys}), {'module_layout': 7})

    def test_partial_or_empty_extended_tables_rejected(self):
        both = tables(b'module_layout\0')
        for sections in ({'__version_ext_crcs': both['__version_ext_crcs']},
                         {'__version_ext_names': (None, b'\0'), '__version_ext_crcs': (None, b'')}):
            with self.subTest(sections=sections), self.assertRaises(ValueError):
                version_crcs(sections)


if __name__ == '__main__':
    unittest.main()
