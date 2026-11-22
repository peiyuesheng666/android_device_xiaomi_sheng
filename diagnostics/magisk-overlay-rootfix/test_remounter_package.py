import unittest

from package_remounter_trial import dq, metadata, replace_hashtrees


class PackageTests(unittest.TestCase):
    STAT = ('Inode: 2860   Type: regular    Mode:  0755   Flags: 0x80000\n'
            'User:     0   Group:  2000   Project: 0   Size: 614624\n'
            'Links: 1   Blockcount: 1168\n'
            'Extended attributes:\n'
            '  security.selinux (26) = "u:object_r:system_file:s0\\000"\n')

    def test_preserve_shell_group(self):
        self.assertEqual(metadata(self.STAT), dict(mode='0755', uid=0, gid=2000,
                                                  xattrs=['security.selinux']))

    def test_reject_nonregular_hardlinks_missing_label(self):
        for text in (self.STAT.replace('Type: regular', 'Type: directory'),
                     self.STAT.replace('Links: 1', 'Links: 2'),
                     self.STAT.replace('  security.selinux', '  unrelated'), '',
                     self.STAT + '  security.capability (20) = "caps"\n'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                metadata(text)

    def test_quote_debugfs_paths(self):
        self.assertEqual(dq('/path with space/"test'), '"/path with space/\\"test"')
        for path in ('/bad\nrm /system/bin/init', '/bad\0path', '/bad\rpath'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                dq(path)

    def test_replace_trees_without_duplicate_properties(self):
        class Tree:
            def __init__(self, name):
                self.partition_name = name
        prop = object()
        old_system, old_ext, product = Tree('system'), Tree('system_ext'), Tree('product')
        new_system, new_ext = Tree('system'), Tree('system_ext')
        old = [prop, old_system, product, old_ext]
        result = replace_hashtrees(old, {'system': new_system, 'system_ext': new_ext}, Tree)
        self.assertEqual(result, [prop, new_system, product, new_ext])
        self.assertEqual(old, [prop, old_system, product, old_ext])
        with self.assertRaises(ValueError):
            replace_hashtrees([prop, old_system, old_system, old_ext], {'system': new_system}, Tree)
        with self.assertRaises(ValueError):
            replace_hashtrees([prop, old_system], {'system_ext': new_ext}, Tree)


if __name__ == '__main__':
    unittest.main()
