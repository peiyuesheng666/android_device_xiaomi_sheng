"""Read exact EROFS inode/xattr bytes without setting host security xattrs.

Layout follows external/erofs-utils/include/erofs_fs.h. Deliberately rejects
long-prefix tables and unknown namespaces rather than losing metadata. File
data integrity and pathname resolution must also be checked by fsck/dump.erofs.
No device access and no writes to an image or host xattrs are performed.
"""
import struct


class ErofsMetadata:
    def __init__(self, data):
        self.data = data
        sb = self.take(1024, 128)
        if struct.unpack_from('<I', sb)[0] != 0xE0F5E1E2:
            raise ValueError('Not EROFS')
        bits = sb[12]
        if bits not in range(9, 17):
            raise ValueError('Unsupported EROFS block size')
        if sb[91]:
            raise ValueError('Long xattr prefix tables require explicit support')
        self.block_size = 1 << bits
        self.metadata_start = struct.unpack_from('<I', sb, 40)[0] * self.block_size
        self.xattr_start = struct.unpack_from('<I', sb, 44)[0] * self.block_size
        self.uuid = bytes(sb[48:64])
        self.build_time = struct.unpack_from('<Q', sb, 24)[0]

    def take(self, offset, length):
        if offset < 0 or length < 0 or offset + length > len(self.data):
            raise ValueError('Out-of-bounds EROFS metadata')
        return self.data[offset:offset + length]

    def entry(self, offset, limit):
        header = self.take(offset, 4)
        namelen, index, size = struct.unpack('<BBH', header)
        prefixes = {1: 'user.', 4: 'trusted.', 6: 'security.'}
        if index not in prefixes or not namelen:
            raise ValueError('Unsupported xattr prefix or empty name')
        end = offset + 4 + namelen + size
        aligned = (end + 3) & ~3
        if aligned > limit:
            raise ValueError('Xattr exceeds its enclosing metadata')
        name = self.take(offset + 4, namelen).decode('ascii')
        if '\0' in name:
            raise ValueError('NUL in xattr name')
        value = self.take(offset + 4 + namelen, size)
        return prefixes[index] + name, bytes(value), aligned

    def inode(self, nid):
        if not isinstance(nid, int) or nid < 0:
            raise ValueError('Invalid EROFS inode identifier')
        offset = self.metadata_start + nid * 32
        compact = self.take(offset, 32)
        fmt, count, mode = struct.unpack_from('<HHH', compact)
        if fmt & ~15:
            raise ValueError('Unknown inode format')
        extended = bool(fmt & 1)
        inode_size = 64 if extended else 32
        raw = self.take(offset, inode_size)
        if extended:
            size = struct.unpack_from('<Q', raw, 8)[0]
            uid, gid = struct.unpack_from('<II', raw, 24)
            links = struct.unpack_from('<I', raw, 44)[0]
        else:
            size = struct.unpack_from('<I', raw, 8)[0]
            uid, gid = struct.unpack_from('<HH', raw, 24)
            links = struct.unpack_from('<H', raw, 6)[0]
        attrs = {}

        def add(entry):
            name, value, _ = entry
            if name in attrs:
                raise ValueError('Duplicate EROFS xattr')
            attrs[name] = value.hex()

        if count:
            body_size = 12 + (count - 1) * 4
            start = offset + inode_size
            body = self.take(start, body_size)
            shared = body[4]
            if 12 + shared * 4 > body_size:
                raise ValueError('Shared xattr list exceeds inode body')
            for i in range(shared):
                index = struct.unpack_from('<I', body, 12 + i * 4)[0]
                add(self.entry(self.xattr_start + index * 4, len(self.data)))
            position, end = start + 12 + shared * 4, start + body_size
            while position < end:
                entry = self.entry(position, end)
                add(entry)
                position = entry[2]
        return dict(mode=mode, uid=uid, gid=gid, links=links, size=size, xattrs=attrs)
