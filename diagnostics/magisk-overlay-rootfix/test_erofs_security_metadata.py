import struct
import unittest

from erofs_security_metadata import ErofsMetadata


def entry(value=b'u:object_r:vendor_file:s0\0', index=6):
    record = struct.pack('<BBH', 7, index, len(value)) + b'selinux' + value
    return record + bytes(-len(record) % 4)


def image(shared=True, extended=True):
    data = bytearray(16384)
    struct.pack_into('<I', data, 1024, 0xE0F5E1E2)
    data[1024 + 12] = 12
    struct.pack_into('<II', data, 1024 + 40, 1, 3)
    base = 4096 + 32
    item = entry()
    count = 2 if shared else 1 + len(item) // 4
    struct.pack_into('<HHH', data, base, int(extended), count, 0o100644)
    struct.pack_into('<Q' if extended else '<I', data, base + 8, 71)
    if extended:
        struct.pack_into('<II', data, base + 24, 12, 34)
        struct.pack_into('<I', data, base + 44, 1)
    else:
        struct.pack_into('<HH', data, base + 24, 12, 34)
        struct.pack_into('<H', data, base + 6, 1)
    attrs = base + (64 if extended else 32)
    if shared:
        data[attrs + 4] = 1
        struct.pack_into('<I', data, attrs + 12, 0)
        data[12288:12288 + len(item)] = item
    else:
        data[attrs + 12:attrs + 12 + len(item)] = item
    return data, base, attrs


class ErofsMetadataTests(unittest.TestCase):
    def test_inline_shared_compact_extended(self):
        for shared in [False, True]:
            for extended in [False, True]:
                data, _, _ = image(shared, extended)
                row = ErofsMetadata(data).inode(1)
                self.assertEqual((row['uid'], row['gid'], row['mode'], row['links'], row['size']), (12, 34, 0o100644, 1, 71))
                self.assertEqual(bytes.fromhex(row['xattrs']['security.selinux']), b'u:object_r:vendor_file:s0\0')

    def test_unknown_prefix_tables_namespaces_and_bounds_refused(self):
        data, base, attrs = image()
        data[1024 + 91] = 1
        with self.assertRaises(ValueError): ErofsMetadata(data)
        data[1024 + 91] = 0
        data[12289] = 0x86
        with self.assertRaises(ValueError): ErofsMetadata(data).inode(1)
        data[12289] = 6
        data[attrs + 4] = 9
        with self.assertRaises(ValueError): ErofsMetadata(data).inode(1)
        with self.assertRaises(ValueError): ErofsMetadata(data).inode(10000)

    def test_duplicate_xattr_refused(self):
        data, base, attrs = image()
        struct.pack_into('<H', data, base + 2, 3)
        data[attrs + 4] = 2
        struct.pack_into('<II', data, attrs + 12, 0, 0)
        with self.assertRaises(ValueError): ErofsMetadata(data).inode(1)

    def test_bad_magic_and_truncation_refused(self):
        with self.assertRaises(ValueError): ErofsMetadata(b'bad')
        data, _, _ = image()
        data[1024] = 0
        with self.assertRaises(ValueError): ErofsMetadata(data)


if __name__ == '__main__': unittest.main()
