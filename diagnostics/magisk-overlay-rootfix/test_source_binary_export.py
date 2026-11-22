import hashlib
import os
from pathlib import Path
import struct
import tempfile
import unittest

from export_source_built_binaries import check_binary, check_static_elf, regular_under


def elf(kind=2, machine=183, types=(1,)):
    header = b'\x7fELF\x02\x01\x01' + bytes(9)
    header += struct.pack('<HHIQQQIHHHHHH', kind, machine, 1, 0, 64, 0, 0,
                          64, 56, len(types), 0, 0, 0)
    return header + b''.join(struct.pack('<IIQQQQQQ', t, 5, 0, 0, 0, 0, 0, 0) for t in types)


class BinaryExportTests(unittest.TestCase):
    def test_static_arm64(self):
        check_static_elf(elf())

    def test_reject_dynamic_wrong_machine_and_truncation(self):
        for data in (elf(kind=3), elf(machine=62), elf(types=(1, 2)),
                     elf(types=(1, 3)), elf(types=(4,)), elf()[:70], b'not elf'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                check_static_elf(data)

    def test_reject_path_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            for relative in ('../outside', '/absolute'):
                with self.subTest(relative=relative), self.assertRaises(ValueError):
                    regular_under(Path(temp), relative)

    def test_distinct_identical_compiler_adapter_staging(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = []
            for name in ('compiler', 'adapter', 'staging'):
                path = root / name
                path.write_bytes(elf())
                path.chmod(0o755)
                rows.append(dict(path=name, bytes=path.stat().st_size,
                                 sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            record = dict(identical=True, static_aarch64_exec=True, executable=True, files=rows)
            self.assertEqual(check_binary(root, record), root / 'staging')
            (root / 'adapter').write_bytes(elf() + b'changed')
            with self.assertRaises(ValueError):
                check_binary(root, record)

    def test_missing_three_distinct_paths(self):
        record = dict(identical=True, static_aarch64_exec=True, executable=True,
                      files=[dict(path='same')] * 3)
        with self.assertRaises(ValueError):
            check_binary(Path('.'), record)

    @unittest.skipIf(os.name == 'nt', 'Native executable and symlink semantics')
    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'original').write_bytes(elf())
            (root / 'link').symlink_to(root / 'original')
            with self.assertRaises(ValueError):
                regular_under(root, 'link')


if __name__ == '__main__':
    unittest.main()
