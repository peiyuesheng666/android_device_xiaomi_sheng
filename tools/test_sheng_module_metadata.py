import unittest

from sheng_module_metadata import format_dependency, parse_dependencies


class AndroidModuleMetadataTest(unittest.TestCase):
    def test_dependency_free_module_does_not_create_directory_dependency(self):
        self.assertEqual(format_dependency('debug_symbol.ko', []), 'debug_symbol.ko:')
        self.assertEqual(parse_dependencies('debug_symbol.ko:\n'), {'debug_symbol.ko': []})

    def test_rejects_real_boot_failure_and_empty_tokens(self):
        for row in ('debug_symbol.ko: ', 'a.ko: b.ko  c.ko', 'a.ko: b.ko\r'):
            with self.subTest(row=row), self.assertRaises(ValueError):
                parse_dependencies(row)

    def test_preserves_depmod_order(self):
        dependencies = ['z.ko', 'b.ko', 'a.ko']
        row = format_dependency('driver.ko', dependencies)
        self.assertEqual(parse_dependencies(row)['driver.ko'], dependencies)


if __name__ == '__main__':
    unittest.main()
