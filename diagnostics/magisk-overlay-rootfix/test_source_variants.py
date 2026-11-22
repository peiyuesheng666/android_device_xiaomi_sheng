import unittest

from materialize_source_variants import checked_copy, safe_relative, sha, transform_crypto_defaults


class VariantTests(unittest.TestCase):
    def test_crypto_source_defaults_rename_only(self):
        old = b'// pinned source list\ncc_defaults {\n    name: "libcrypto_sources",\n    srcs: ["src/crypto/a.cc"],\n}\n'
        new = transform_crypto_defaults(old, 'crypto-generated-defaults')
        self.assertEqual(new.replace(b'sheng_first_stage_', b''), old)
        with self.assertRaises(ValueError):
            transform_crypto_defaults(old, 'unknown')

    def test_crypto_main_defaults_preserve_flags_and_fail_on_missing_block(self):
        names = ('boringssl_flags_common', 'boringssl_flags',
                 'boringssl_defaults', 'libcrypto_defaults')
        old = ''.join('cc_defaults {\n    name: "' + name + '",\n'
                      '    cflags: ["-DKEEP_SECURITY_FLAGS"],\n}\n\n' for name in names).encode()
        result = transform_crypto_defaults(old, 'crypto-main-defaults')
        self.assertEqual(result.count(b'-DKEEP_SECURITY_FLAGS'), 4)
        for name in names:
            self.assertIn(('"sheng_first_stage_' + name + '"').encode(), result)
        with self.assertRaises(AssertionError):
            transform_crypto_defaults(b'cc_defaults {\n name: "incomplete",\n}\n',
                                      'crypto-main-defaults')

    def test_reject_drift_instead_of_repinning(self):
        with self.assertRaises(ValueError):
            checked_copy(b'changed', sha(b'original'), 'source')
        self.assertEqual(checked_copy(b'original', sha(b'original'), 'source'), b'original')

    def test_safe_paths(self):
        self.assertEqual(safe_relative('interfaces/compat/foo.cpp').as_posix(), 'interfaces/compat/foo.cpp')
        for path in ('', '.', '../public/source', '/etc/passwd', 'C:/source', r'..\public'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                safe_relative(path)


if __name__ == '__main__':
    unittest.main()
