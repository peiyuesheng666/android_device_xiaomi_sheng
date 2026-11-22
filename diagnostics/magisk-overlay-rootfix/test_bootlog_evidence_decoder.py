"""Exercise the existing disk-log decoder against the actual v1 record format."""
from pathlib import Path
import struct
import sys
import unittest
import zlib

sys.path.insert(0,str(Path(__file__).resolve().parents[5]/'scripts'))
from read_sheng618_disklog import decode

SLOT = 1024**2


def record(*, run=0x1234, sequence=7, text=b'init: evidence\n', version=1,
           header=64, total=4096, reserved=0, padding=bytes(8)):
    data = bytearray(SLOT)
    data[:64] = struct.pack('<8sIIQQQIIII8s',b'SH618LOG',version,header,
        run,sequence,42000,len(text),zlib.crc32(text),total,reserved,padding)
    data[64:64+len(text)] = text
    if 80 <= total <= SLOT:
        data[total-16:total] = struct.pack('<8sQ',b'SH618END',sequence)
    return bytes(data)


class DisklogEvidenceTests(unittest.TestCase):
    def test_two_slots_preserve_separate_run_and_sequence(self):
        rows = decode(record()+record(run=0x5678,sequence=8,text=b'panic: trace\n'))
        self.assertEqual([(r['slot'],r['run'],r['sequence']) for r in rows],
            [(0,'0000000000001234',7),(1,'0000000000005678',8)])
        self.assertEqual(rows[0]['text'],'init: evidence\n')
        self.assertEqual(rows[1]['uptime_ms'],42000)

    def test_bad_header_and_bounds_rejected(self):
        for changes in (dict(version=2),dict(header=63),dict(total=4095),
                        dict(total=0),dict(total=SLOT+4096),dict(reserved=1),dict(padding=b'x'*8)):
            with self.subTest(changes=changes):
                self.assertEqual(decode(record(**changes)+bytes(SLOT)),[])

    def test_crc_corruption_rejected_without_hiding_other_slot(self):
        bad = bytearray(record()); bad[64] ^= 1
        rows = decode(bytes(bad)+record(sequence=9))
        self.assertEqual([(r['slot'],r['sequence']) for r in rows],[(1,9)])

    def test_torn_commit_or_wrong_sequence_rejected(self):
        for offset in (4096-16,4096-8):
            bad=bytearray(record()); bad[offset] ^= 1
            with self.subTest(offset=offset):
                self.assertEqual(decode(bytes(bad)+bytes(SLOT)),[])

    def test_text_must_fit_before_footer(self):
        bad=bytearray(record())
        struct.pack_into('<I',bad,40,4096-79)
        self.assertEqual(decode(bytes(bad)+bytes(SLOT)),[])

    def test_nonrecord_and_short_header_rejected(self):
        self.assertEqual(decode(bytes(2*SLOT)),[])
        self.assertEqual(decode(b'SH618LOG'),[])


if __name__ == '__main__':
    unittest.main()
