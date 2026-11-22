import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile
import zlib
from sheng_apk_components import compiled_components, dex_classes, verify_apk_components

SOURCE='<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="app.test"><application><service android:name=".Tile"/></application></manifest>'
DUMP='''E: manifest
  A: package="app.test"
  E: application
    E: service
      A: android:name(0x01010003)=".Tile"
      E: meta-data
        A: android:name(0x01010003)="not.a.Class"
'''


def dex(define=True):
    name=b'Lapp/test/Tile;'
    data=bytearray(152+len(name)+2)
    data[:8]=b'dex\n035\0'
    struct.pack_into('<III',data,32,len(data),112,0x12345678)
    struct.pack_into('<IIII',data,56,1,112,1,116)
    struct.pack_into('<II',data,96,1 if define else 0,120)
    struct.pack_into('<I',data,112,152)
    data[152]=len(name);data[153:153+len(name)]=name
    data[12:32]=hashlib.sha1(data[32:]).digest()
    struct.pack_into('<I',data,8,zlib.adler32(data[12:]))
    return bytes(data)


class ComponentTests(unittest.TestCase):
    def apk(self, payload):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        path=Path(temp.name)/'test.apk'
        with zipfile.ZipFile(path,'w') as z:z.writestr('classes.dex',payload)
        return path

    def test_real_class_definition(self):
        q=verify_apk_components(self.apk(dex()),DUMP,SOURCE)
        self.assertTrue(q['manifest_classes_defined'])

    def test_reference_string_is_not_class_definition(self):
        with self.assertRaisesRegex(ValueError,'no DEX class'):
            verify_apk_components(self.apk(dex(False)),DUMP,SOURCE)

    def test_compiled_manifest_must_match_source(self):
        with self.assertRaisesRegex(ValueError,'differ from source'):
            verify_apk_components(self.apk(dex()),'E: manifest\n  A: package="app.test"',SOURCE)

    def test_metadata_names_not_component_classes(self):
        self.assertEqual(compiled_components(DUMP),{'app.test.Tile'})

    def test_bad_integrity(self):
        data=bytearray(dex());data[-1]^=1
        with self.assertRaisesRegex(ValueError,'integrity'):
            dex_classes(data)


if __name__=='__main__':unittest.main()
