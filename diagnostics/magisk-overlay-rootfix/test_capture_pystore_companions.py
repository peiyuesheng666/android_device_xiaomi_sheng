import hashlib
import struct
import unittest
from capture_pystore_companions import parse_slot


def fixture():
    data=bytearray(1024**2)
    geometry=bytearray(52)
    struct.pack_into('<II',geometry,0,0x616c4467,52)
    struct.pack_into('<III',geometry,40,65536,2,4096)
    geometry[8:40]=hashlib.sha256(geometry).digest()
    data[4096:4096+52]=geometry
    data[8192:8192+52]=geometry
    for slot,name in enumerate((b'system_a',b'vendor_b-cow')):
        tables=(struct.pack('<36s4I',name,1,0,1,0)+
                struct.pack('<QIQI',16,0,2048,0)+
                struct.pack('<36sIQ',b'group',0,64*1024**2)+
                struct.pack('<QIIQ36sI',2048,1048576,0,64*1024**2,b'super',0))
        header=bytearray(128)
        struct.pack_into('<IHHI',header,0,0x414c5030,10,2,128)
        struct.pack_into('<I',header,44,len(tables))
        header[48:80]=hashlib.sha256(tables).digest()
        for offset,first,width in ((80,0,52),(92,52,24),(104,76,48),(116,124,64)):
            struct.pack_into('<III',header,offset,first,1,width)
        header[12:44]=hashlib.sha256(header).digest()
        for index in (slot,2+slot):
            start=12288+index*65536
            data[start:start+len(header)+len(tables)]=header+tables
    return data


class SlotTests(unittest.TestCase):
    def test_selects_slot_one_and_accepts_cow_names(self):
        self.assertEqual(parse_slot(fixture(),64*1024**2,1)['partitions'][0]['name'],'vendor_b-cow')
        self.assertEqual(parse_slot(fixture(),64*1024**2,0)['partitions'][0]['name'],'system_a')

    def test_rejects_corruption_in_geometry_header_tables_or_backup(self):
        for offset in (4096+40,8192+40,12288+65536+80,12288+65536+128,12288+3*65536+128):
            data=fixture();data[offset]^=1
            with self.subTest(offset=offset),self.assertRaises(AssertionError):
                parse_slot(data,64*1024**2,1)

    def test_rejects_wrong_physical_size_and_slot(self):
        for size,slot in ((32*1024**2,1),(64*1024**2,2)):
            with self.subTest(size=size,slot=slot),self.assertRaises(AssertionError):
                parse_slot(fixture(),size,slot)


if __name__=='__main__':
    unittest.main()
