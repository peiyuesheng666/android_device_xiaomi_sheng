#!/usr/bin/env python3
"""Compile the production record validator; exercise valid/corrupt disk inputs.

Host record-format tests only: not kernel I/O, procfs, SELinux or hardware tests.
"""
import ctypes
import errno
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zlib

SOURCE = Path(__file__).resolve().parents[1] / 'interfaces/kernel/6.18/sheng_bootlog.c'
SLOT = 5 * 1024 * 1024


def extract(source, signature, suffix=''):
    start = source.index(signature)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end] + suffix


def record(text=b'kernel boot test\n', sequence=7, version=2):
    b = bytearray(SLOT)
    total = (64 + len(text) + 16 + 4095) & ~4095
    struct.pack_into('<8sIIQQQIIII8s', b, 0, b'SH618LOG', version, 64, 123,
                     sequence, 1000, len(text), zlib.crc32(text), total, 0, b'')
    b[64:64 + len(text)] = text
    struct.pack_into('<8sQ', b, total - 16, b'SH618END', sequence)
    return b


class PystoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='sheng-pystore-test-')
        s = SOURCE.read_text()
        harness = r'''
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
typedef uint32_t __le32;
typedef uint64_t __le64;
#define __packed __attribute__((packed))
#define IS_ALIGNED(v,a) (((v) & ((a)-1)) == 0)
#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
#define le32_to_cpu(v) (v)
#else
#define le32_to_cpu(v) __builtin_bswap32(v)
#endif
static u32 crc32_le(u32 crc, const void *data, size_t bytes) {
    const unsigned char *p=data;
    while (bytes--) {
        crc ^= *p++;
        for (int i=0; i<8; i++) crc=(crc>>1)^((0U-(crc&1))&0xedb88320U);
    }
    return crc;
}
'''
        for name in ('SLOT_BYTES', 'LEGACY_SLOT_BYTES'):
            harness += next(line for line in s.splitlines()
                            if line.startswith('#define ' + name + ' ')) + '\n'
        harness += extract(s, 'struct bootlog_header {', ' __packed;\n')
        harness += extract(s, 'struct bootlog_end {', ' __packed;\n')
        harness += extract(s, 'static int pystore_validate(')
        harness += '\nint validate(const char *r, size_t n, size_t *t) { return pystore_validate(r,n,t); }\n'
        cpp = Path(cls.tmp.name) / 'validator.c'
        lib = Path(cls.tmp.name) / 'validator.so'
        cpp.write_text(harness)
        subprocess.run(['cc', '-shared', '-fPIC', '-Wall', '-Werror', '-O2',
                        str(cpp), '-o', str(lib)], check=True)
        cls.lib = ctypes.CDLL(str(lib))
        cls.lib.validate.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                     ctypes.POINTER(ctypes.c_size_t)]
        cls.lib.validate.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def check(self, b, length=None):
        buf = ctypes.create_string_buffer(bytes(b))
        text = ctypes.c_size_t(0)
        result = self.lib.validate(buf, len(b) if length is None else length,
                                   ctypes.byref(text))
        return result, text.value

    def test_valid(self):
        self.assertEqual(self.check(record()), (0, len(b'kernel boot test\n')))

    def test_legacy(self):
        b = record(version=1)
        self.assertEqual(self.check(b)[0], 0)
        self.assertEqual(self.check(b[:1024*1024])[0], 0)
        self.assertEqual(self.check(record(b'x'*(1024*1024), version=1))[0], -errno.EBADMSG)

    def test_boot_only(self):
        s = SOURCE.read_text()
        capture = extract(s, 'static void capture_snapshot(void)\n{')
        self.assertLess(capture.index('READ_ONCE(boot_complete)'), capture.index('capture_early_trace();'))
        self.assertIn('!READ_ONCE(boot_complete)', extract(s, 'static int snapshot_thread('))
        finish = extract(s, 'static int finish_boot(')
        self.assertLess(finish.index('capture_snapshot();'), finish.index('WRITE_ONCE(boot_complete, true)'))
        self.assertIn('if (!done)', finish)

    def test_device_boot_completion_integration(self):
        root = SOURCE.parents[3]
        rc = (root / 'rootdir/etc/init.sheng.rc').read_text()
        self.assertIn('on property:sys.boot_completed=1\n'
                      '    write /sys/module/sheng_bootlog/parameters/boot_complete 1', rc)
        contexts = (root / 'sepolicy/vendor/genfs_contexts').read_text()
        self.assertIn('/module/sheng_bootlog/parameters/boot_complete '
                      'u:object_r:vendor_sysfs_sheng_boot_complete:s0', contexts)
        policy = (root / 'sepolicy/vendor/vendor_init.te').read_text()
        self.assertIn('allow vendor_init vendor_sysfs_sheng_boot_complete:file', policy)

    def test_empty_slot(self):
        self.assertEqual(self.check(bytearray(SLOT))[0], -errno.ENODATA)

    def test_short_read(self):
        self.assertEqual(self.check(record(), SLOT-1)[0], -errno.ENODATA)

    def test_bad_header_fields(self):
        for offset, value in ((8,3),(12,63),(40,0xffffffff),
                              (48,0),(48,4095),(48,SLOT+4096)):
            with self.subTest(offset=offset, value=value):
                b = record()
                struct.pack_into('<I', b, offset, value)
                self.assertEqual(self.check(b)[0], -errno.EBADMSG)

    def test_bad_crc(self):
        b = record()
        b[64] ^= 1
        self.assertEqual(self.check(b)[0], -errno.EBADMSG)

    def test_bad_footer(self):
        for offset in (4096-16, 4096-8):
            b = record()
            b[offset] ^= 1
            self.assertEqual(self.check(b)[0], -errno.EBADMSG)

    def test_maximum_payload(self):
        self.assertEqual(self.check(record(b'x'*(SLOT-80))), (0,SLOT-80))

    def test_preserve_registration_order_and_read_only(self):
        s = SOURCE.read_text()
        init = extract(s, 'static int __init sheng_bootlog_init(')
        self.assertLess(init.index('pystore_init();'), init.index('if (!enabled)'))
        ops = s[s.index('static const struct proc_ops pystore_ops'):]
        self.assertNotIn('.proc_write', ops[:ops.index('};')])


if __name__ == '__main__':
    unittest.main()
