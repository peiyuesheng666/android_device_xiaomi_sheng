#!/usr/bin/env python3
"""Negative tests for the current-pair provider gate; no hardware access."""
import unittest

from package_sheng_dp_current_pair import check_imports


class Module:
    def __init__(self, versions, undefined=()):
        self._versions = versions
        self._undefined = set(undefined)

    def versions(self):
        return self._versions

    def undefined(self):
        return self._undefined


class ImportGateTest(unittest.TestCase):
    def setUp(self):
        self.providers = {'module_layout': [('vmlinux', 1)], 'function': [('provider.ko', 2)]}

    def test_matching_actual_providers(self):
        self.assertEqual(check_imports(Module({'module_layout': 1, 'function': 2}, ['function']),
                                       self.providers), [])

    def test_missing_module_layout_is_not_compatibility(self):
        with self.assertRaises(AssertionError):
            check_imports(Module({}), self.providers)

    def test_mismatched_crc(self):
        with self.assertRaises(AssertionError):
            check_imports(Module({'module_layout': 3}), self.providers)

    def test_missing_provider(self):
        with self.assertRaises(AssertionError):
            check_imports(Module({'module_layout': 1, 'absent': 2}), self.providers)

    def test_duplicate_provider(self):
        self.providers['module_layout'].append(('duplicate.ko', 1))
        with self.assertRaises(AssertionError):
            check_imports(Module({'module_layout': 1}), self.providers)

    def test_unresolved_global(self):
        with self.assertRaises(AssertionError):
            check_imports(Module({'module_layout': 1}, ['absent']), self.providers)

    def test_unversioned_import_is_reported_not_crc_proven(self):
        self.assertEqual(check_imports(Module({'module_layout': 1}, ['function']), self.providers),
                         ['function'])


if __name__ == '__main__':
    unittest.main()
