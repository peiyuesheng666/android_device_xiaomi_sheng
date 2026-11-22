import os
from pathlib import Path
import tempfile
import unittest

from check_file_context_lookups import check


@unittest.skipUnless(os.name == 'posix', 'Requires Linux libselinux; run in WSL')
class LookupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'file_contexts'
        self.path.write_text('/test(/.*)? u:object_r:base_file:s0\n'
                             '/test/exact(/.*)? u:object_r:exact_file:s0\n')

    def tearDown(self):
        self.directory.cleanup()

    def test_full_database_precedence(self):
        result = check(self.path, [('/test/exact/67', 'exact_file'), ('/test/other', 'base_file')])
        self.assertEqual(len(result), 2)
        self.assertTrue(all(row['passed'] for row in result))

    def test_expected_type_mismatch_fails(self):
        with self.assertRaises(RuntimeError):
            check(self.path, [('/test/exact', 'wrong_file')])

    def test_missing_path_fails(self):
        with self.assertRaises(OSError):
            check(self.path, [('/missing', 'base_file')])

    def test_invalid_database_fails(self):
        self.path.write_text('/test[ u:object_r:base_file:s0\n')
        with self.assertRaises(OSError):
            check(self.path, [('/test', 'base_file')])


if __name__ == '__main__':
    unittest.main()
