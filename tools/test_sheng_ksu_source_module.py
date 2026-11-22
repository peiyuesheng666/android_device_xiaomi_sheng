#!/usr/bin/env python3
"""Focused parsing/negative tests; not a runtime or complete ABI test."""
import struct
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audit_sheng_ksu_source_module import audit, runtime_name, version_crcs


def extended(names, values):
    return {'__version_ext_names': (1, names),
            '__version_ext_crcs': (1, struct.pack('<' + 'I' * len(values), *values))}


class VersionTests(unittest.TestCase):
    def test_extended(self):
        self.assertEqual(version_crcs(extended(b'module_layout\0_printk\0', [0x1234, 7])),
                         {'module_layout': 0x1234, '_printk': 7})

    def test_basic(self):
        row = struct.pack('<Q', 0x1234) + b'module_layout\0'.ljust(56, b'\0')
        self.assertEqual(version_crcs({'__versions': (1, row)}), {'module_layout': 0x1234})

    def test_reject_empty_or_missing(self):
        for data in ({}, {'__versions': (1, b'')}, extended(b'\0', [])):
            with self.subTest(data=data), self.assertRaises(ValueError):
                version_crcs(data)

    def test_reject_corrupt_tables(self):
        cases = [extended(b'module_layout', [1]), extended(b'module_layout\0', [1, 2]),
                 extended(b'module_layout\0module_layout\0', [1, 1]),
                 extended(b'_printk\0', [1]), {'__versions': (1, b'x')},
                 {'__version_ext_names': (1, b'module_layout\0')},
                 {'__version_ext_crcs': (1, b'123')},
                 extended(b'module_layout\0\0', [1, 1])]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ValueError):
                version_crcs(data)

    def test_reject_ambiguous_modes(self):
        data = extended(b'module_layout\0', [1])
        data['__versions'] = (1, b'x' * 64)
        with self.assertRaises(ValueError):
            version_crcs(data)

    def test_reject_out_of_range_basic_crc(self):
        row = struct.pack('<Q', 1 << 40) + b'module_layout\0'.ljust(56, b'\0')
        with self.assertRaises(ValueError):
            version_crcs({'__versions': (1, row)})

    def test_runtime_name_matches_pinned_ksuinit(self):
        self.assertEqual(runtime_name('symbol'), 'symbol')
        self.assertEqual(runtime_name('symbol.llvm.12'), 'symbol')
        self.assertEqual(runtime_name('symbol$123'), 'symbol')
        self.assertEqual(runtime_name('symbol.llvm.12$123'), 'symbol.llvm.12')


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.module, self.kernel, self.symvers = (root / n for n in ('module', 'kernel', 'symvers'))
        self.module.write_bytes(b'\0' * 16 + struct.pack('<HH', 1, 183))
        self.kernel.write_bytes(b'fixture kernel, mocked nm only')
        self.symvers.write_text('0x1\tmodule_layout\tvmlinux\tEXPORT_SYMBOL\n'
                                '0x2\ttest_sym\tvmlinux\tEXPORT_SYMBOL_GPL\tTEST_NS\n')
        self.data = extended(b'module_layout\0test_sym\0', [1, 2])
        self.data['.modinfo'] = (1, b'vermagic=6.18-test SMP\0license=GPL\0import_ns=TEST_NS\0')
        self.undefined = 'test_sym U\nksu_private U\n'
        self.defined = 'test_sym T 1000 4\nksu_private D 2000 4\n'

    def run_audit(self):
        with patch('audit_sheng_ksu_source_module.sections', return_value=self.data), \
             patch('audit_sheng_ksu_source_module.subprocess.check_output',
                   side_effect=[self.undefined, self.defined]):
            return audit(self.module, self.kernel, self.symvers, '6.18-test', Path('mock-nm'))

    def test_positive_does_not_claim_runtime(self):
        result = self.run_audit()
        self.assertTrue(result['passed'])
        self.assertEqual(result['private_prelink_references'], ['ksu_private'])
        self.assertFalse(result['complete_abi_proven'])
        self.assertFalse(result['runtime_verified'])

    def test_reject_crc_mismatch(self):
        self.data.update(extended(b'module_layout\0test_sym\0', [1, 3]))
        with self.assertRaisesRegex(ValueError, 'CRC mismatch'):
            self.run_audit()

    def test_reject_missing_exported_crc(self):
        self.data.update(extended(b'module_layout\0', [1]))
        with self.assertRaisesRegex(ValueError, 'Missing CRCs'):
            self.run_audit()

    def test_reject_missing_import(self):
        self.data['.modinfo'] = (1, b'vermagic=6.18-test SMP\0license=GPL\0')
        with self.assertRaisesRegex(ValueError, 'namespace imports'):
            self.run_audit()

    def test_reject_absent_private_symbol(self):
        self.defined = 'test_sym T 1000 4\n'
        with self.assertRaisesRegex(ValueError, 'Runtime symbols absent'):
            self.run_audit()

    def test_reject_ambiguous_runtime_symbol(self):
        self.defined += 'ksu_private.llvm.123 D 3000 4\n'
        with self.assertRaisesRegex(ValueError, 'ambiguous='):
            self.run_audit()

    def test_reject_wrong_release(self):
        self.data['.modinfo'] = (1, b'vermagic=6.12-old SMP\0license=GPL\0import_ns=TEST_NS\0')
        with self.assertRaisesRegex(ValueError, 'Wrong kernel release'):
            self.run_audit()

    def test_reject_wrong_architecture(self):
        self.module.write_bytes(b'\0' * 16 + struct.pack('<HH', 1, 62))
        with self.assertRaisesRegex(ValueError, 'arm64'):
            self.run_audit()


if __name__ == '__main__':
    unittest.main()
