"""Check real DEX class definitions against source and compiled app components."""
import hashlib
import re
import struct
import xml.etree.ElementTree as ET
import zlib
import zipfile

TAGS = {'application', 'activity', 'service', 'receiver', 'provider'}
ANDROID = '{http://schemas.android.com/apk/res/android}'


def qualify_name(package, name):
    return package+name if name.startswith('.') else name if '.' in name else package+'.'+name


def source_components(text):
    root = ET.fromstring(text)
    package = root.attrib['package']
    return {qualify_name(package, node.attrib[ANDROID+'name']) for node in root.iter()
            if node.tag in TAGS and ANDROID+'name' in node.attrib}


def compiled_components(text):
    package = re.search(r'^\s*A: package="([^"]+)"', text, re.M)
    if not package:
        raise ValueError('No package in official aapt2 manifest dump')
    result, stack = set(), []
    for line in text.splitlines():
        tag = re.match(r'^(\s*)E: ([^\s(]+)', line)
        if tag:
            depth = len(tag[1])
            while stack and stack[-1][0] >= depth:
                stack.pop()
            stack.append((depth, tag[2]))
        name = re.search(r'A: (?:android|http://schemas.android.com/apk/res/android):name\([^)]*\)="([^"]+)"', line)
        if name and stack and stack[-1][1] in TAGS:
            result.add(qualify_name(package[1], name[1]))
    return result


def dex_classes(data):
    if len(data) < 112 or data[:4] != b'dex\n' or data[7] != 0:
        raise ValueError('Expected standard DEX')
    if struct.unpack_from('<I', data, 32)[0] != len(data) or struct.unpack_from('<I', data, 40)[0] != 0x12345678:
        raise ValueError('Malformed DEX header')
    if data[12:32] != hashlib.sha1(data[32:]).digest() or struct.unpack_from('<I', data, 8)[0] != zlib.adler32(data[12:]):
        raise ValueError('DEX integrity check failed')
    strings, string_offset, types, type_offset = struct.unpack_from('<IIII', data, 56)
    classes, class_offset = struct.unpack_from('<II', data, 96)
    for count, offset, size in ((strings,string_offset,4),(types,type_offset,4),(classes,class_offset,32)):
        if offset+count*size > len(data):
            raise ValueError('DEX table out of bounds')
    result = set()
    for i in range(classes):
        index = struct.unpack_from('<I', data, class_offset+i*32)[0]
        if index >= types:
            raise ValueError('Invalid DEX class type index')
        index = struct.unpack_from('<I', data, type_offset+index*4)[0]
        if index >= strings:
            raise ValueError('Invalid DEX descriptor string index')
        pos = struct.unpack_from('<I', data, string_offset+index*4)[0]
        for _ in range(5):
            if pos >= len(data): raise ValueError('Truncated DEX string length')
            byte = data[pos]; pos += 1
            if not byte & 0x80: break
        else: raise ValueError('Invalid DEX string length')
        end = data.find(b'\0', pos)
        if end < 0: raise ValueError('Unterminated DEX descriptor')
        name = data[pos:end].decode('ascii')
        if not name.startswith('L') or not name.endswith(';') or name in result:
            raise ValueError('Invalid or duplicate DEX class definition')
        result.add(name)
    return result


def verify_apk_components(apk, manifest_dump, source_manifest):
    expected = source_components(source_manifest)
    declared = compiled_components(manifest_dump)
    if expected != declared:
        raise ValueError('APK components differ from source manifest: missing='+repr(sorted(expected-declared))+' extra='+repr(sorted(declared-expected)))
    classes = set()
    with zipfile.ZipFile(apk) as archive:
        for name in archive.namelist():
            if re.fullmatch(r'classes(?:[2-9]|[1-9][0-9]+)?\.dex', name):
                current = dex_classes(archive.read(name))
                if current & classes: raise ValueError('Duplicate class across DEX files')
                classes.update(current)
    required = {'L'+name.replace('.','/')+';' for name in declared}
    if required-classes:
        raise ValueError('Manifest component has no DEX class definition: '+repr(sorted(required-classes)))
    return dict(manifest_components=sorted(declared),dex_class_count=len(classes),manifest_classes_defined=True,source_manifest_matches=True)
