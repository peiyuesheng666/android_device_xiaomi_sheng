#!/usr/bin/env python3
"""Read-only inventory of AArch64 vendor C2 field-vector definitions and users."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import subprocess


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor-tree', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--readelf', required=True, help='LLVM readelf with Android packed relocation support')
    args = parser.parse_args()
    root = args.vendor_tree.resolve(strict=True)
    assert root.is_dir() and not args.output.exists()
    inputs, symlinks = [], []
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            symlinks.append(str(path.relative_to(root)))
            continue
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            header = stream.read(20)
        if (len(header) == 20 and header[:6] == b'\x7fELF\x02\x01'
                and struct.unpack_from('<HH', header, 16)[0] in (2, 3)
                and struct.unpack_from('<H', header, 18)[0] == 183):
            inputs.append(path)

    def inspect(path):
        result = subprocess.run([args.readelf, '--dyn-syms', '--relocs', '--wide', str(path)],
                                text=True, capture_output=True, check=True)
        vectors, api, references = {}, [], []
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) >= 5 and fields[2].startswith('R_AARCH64_'):
                name = fields[4].split('@', 1)[0]
                if name.endswith('11_FIELD_LISTE'):
                    references.append(dict(offset=fields[0], type=fields[2], name=name))
            if len(fields) < 8 or not fields[0].endswith(':') or not fields[0][:-1].isdigit():
                continue
            name = fields[7].split('@', 1)[0]
            entry = dict(value=fields[1], size=int(fields[2], 16 if fields[2].startswith('0x') else 10), type=fields[3],
                         binding=fields[4], visibility=fields[5], section=fields[6])
            if name.endswith('11_FIELD_LISTE'):
                vectors[name] = entry
            elif 'C2FieldList' in name or 'C2ParamUtils' in name:
                api.append(dict(name=name, **entry))
        return dict(path=str(path.relative_to(root)), vectors=vectors, field_api=api,
                    field_vector_relocations=references)

    with ThreadPoolExecutor(max_workers=2) as executor:
        records = list(executor.map(inspect, inputs))
    by_path = {record['path']: record for record in records}
    filterbase = by_path['lib64/libqcodec2_filterbase.so']['vectors']
    vndk = by_path['lib64/libcodec2_vndk.so']['vectors']

    def global_object(entry):
        return (entry['type'] == 'OBJECT' and entry['binding'] == 'GLOBAL'
                and entry['visibility'] == 'DEFAULT' and entry['section'] != 'UND')

    collisions = sorted(name for name in filterbase.keys() & vndk.keys()
                        if global_object(filterbase[name]) and global_object(vndk[name]))
    for path in ('lib64/libqcodec2_filterbase.so', 'lib64/libcodec2_vndk.so'):
        assert by_path[path]['field_vector_relocations'], \
            'readelf did not decode the known Android packed field-vector relocations'
    relevant = []
    for record in records:
        if not record['vectors'] and not record['field_api']:
            continue
        record['sha256'] = sha(root / record['path'])
        record['collision_imports'] = sorted(name for name, entry in record['vectors'].items()
                                             if name in collisions and entry['section'] == 'UND')
        record['collision_definitions'] = sorted(name for name, entry in record['vectors'].items()
                                                 if name in collisions and entry['section'] != 'UND')
        relevant.append(record)
    output = dict(date_utc=datetime.now(timezone.utc).isoformat(), kind='static-c2-fieldlist-inventory',
                  tool_sha256=sha(Path(__file__)), vendor_tree=str(root), readelf=args.readelf,
                  scanned_elf_count=len(inputs),
                  skipped_symlinks=symlinks, collision_symbols=collisions, records=relevant,
                  installed=False, hardware_tested=False, boot_failure_cause_established=False,
                  provider_abi_validated=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(output, stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(scanned_elf_count=len(inputs), collision_count=len(collisions),
                          relevant_elf_count=len(relevant),
                          importing_files=[r['path'] for r in relevant if r['collision_imports']]), indent=2))


if __name__ == '__main__':
    main()
