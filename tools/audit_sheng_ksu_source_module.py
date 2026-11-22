#!/usr/bin/env python3
"""Audit a source-matched KSU LKM without loading it.

KSU's pinned ksuinit resolves private symbols before init_module(). An ordinary
export-table check therefore cannot certify this module. Require every runtime
name to resolve uniquely AND retain/check real MODVERSIONS data, including
module_layout. Empty generic-DDK version tables are deliberately rejected.
This is offline evidence, never a claim of runtime or complete ABI acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess

from sheng_kernel_image import sections


def version_crcs(elf_sections):
    """Decode basic or extended Linux modversions, rejecting malformed tables."""
    ext = '__version_ext_crcs' in elf_sections or '__version_ext_names' in elf_sections
    basic = []
    raw = elf_sections.get('__versions', (None, b''))[1]
    if len(raw) % 64:
        raise ValueError('Malformed arm64 basic versions')
    for offset in range(0, len(raw), 64):
        value = struct.unpack_from('<Q', raw, offset)[0]
        field = raw[offset + 8:offset + 64]
        if value > 0xffffffff or b'\0' not in field:
            raise ValueError('Invalid basic version record')
        basic.append((field.split(b'\0', 1)[0], value))
    rows = basic
    if ext:
        if not all(k in elf_sections for k in ('__version_ext_crcs', '__version_ext_names')):
            raise ValueError('Incomplete extended version sections')
        crc = elf_sections['__version_ext_crcs'][1]
        names = elf_sections['__version_ext_names'][1]
        if not crc or len(crc) % 4 or not names.endswith(b'\0'):
            raise ValueError('Empty or malformed extended versions')
        count = len(crc) // 4
        fields = names.split(b'\0', count)
        # Accept section padding only after the exact number of CRC-indexed names.
        if len(fields) != count + 1 or any(fields[-1]) or not all(fields[:-1]):
            raise ValueError('Extended name/CRC count mismatch')
        rows = list(zip(fields[:-1], struct.unpack('<' + 'I' * count, crc)))
        if basic and basic != rows:
            raise ValueError('Basic and extended version tables disagree')
    if not rows:
        raise ValueError('Empty/missing versions are not source-matched CRC evidence')
    result = {}
    for raw_name, value in rows:
        name = raw_name.decode('ascii')
        if not name or name in result:
            raise ValueError('Empty/duplicate version name')
        result[name] = value
    if 'module_layout' not in result:
        raise ValueError('Missing module_layout CRC')
    return result


def runtime_name(name):
    # Keep this identical to pinned ksuinit::kernel_symbols_iter().
    if '$' in name:
        return name.split('$', 1)[0]
    return name.split('.llvm.', 1)[0]


def audit(module, vmlinux, symvers, release, llvm_nm):
    raw = module.read_bytes()
    if len(raw) < 20 or struct.unpack_from('<HH', raw, 16) != (1, 183):
        raise ValueError('Expected arm64 relocatable module')
    elf_sections = sections(raw)
    crcs = version_crcs(elf_sections)
    exports = {}
    for line in symvers.read_text().splitlines():
        row = line.split()
        if len(row) < 4 or row[1] in exports:
            raise ValueError('Malformed/duplicate Module.symvers entry')
        exports[row[1]] = dict(crc=int(row[0], 16), namespace=row[4] if len(row) > 4 else '')
    mismatches = [name for name, crc in crcs.items()
                  if name not in exports or exports[name]['crc'] != crc]
    if mismatches:
        raise ValueError('CRC mismatch: ' + ', '.join(mismatches))
    modinfo = elf_sections.get('.modinfo', (0, b''))[1].split(b'\0')
    modinfo = [entry.decode('ascii') for entry in modinfo if entry]
    magic = [entry.removeprefix('vermagic=') for entry in modinfo if entry.startswith('vermagic=')]
    if len(magic) != 1 or not magic[0].split() or magic[0].split()[0] != release:
        raise ValueError('Wrong kernel release in vermagic')
    imports = {entry.removeprefix('import_ns=') for entry in modinfo if entry.startswith('import_ns=')}
    if 'license=GPL' not in modinfo:
        raise ValueError('Expected KSU GPL module license')
    command = [str(llvm_nm), '--undefined-only', '--format=posix', str(module)]
    undefined = [line.split()[0] for line in subprocess.check_output(command, text=True).splitlines()
                 if line.strip()]
    symbols = {}
    text = subprocess.check_output([str(llvm_nm), '--defined-only', '--format=posix', str(vmlinux)], text=True)
    for line in text.splitlines():
        row = line.split()
        if len(row) >= 3:
            key = runtime_name(row[0])
            if key in undefined:
                symbols.setdefault(key, set()).add(int(row[2], 16))
    unresolved = [name for name in undefined if not symbols.get(name)]
    ambiguous = [name for name in undefined if len(symbols.get(name, ())) > 1]
    if unresolved or ambiguous:
        raise ValueError(f'Runtime symbols absent={unresolved}, ambiguous={ambiguous}')
    missing_crcs = [name for name in undefined if name in exports and name not in crcs]
    missing_imports = sorted({exports[name]['namespace'] for name in undefined
                              if name in exports and exports[name]['namespace']
                              and exports[name]['namespace'] not in imports})
    if missing_crcs or missing_imports:
        raise ValueError(f'Missing CRCs={missing_crcs}, namespace imports={missing_imports}')
    return dict(passed=True, scope='Offline source-matched KSU LKM metadata and symbol audit only',
                module_sha256=hashlib.sha256(raw).hexdigest(),
                vmlinux_sha256=hashlib.sha256(vmlinux.read_bytes()).hexdigest(),
                symvers_sha256=hashlib.sha256(symvers.read_bytes()).hexdigest(),
                crc_entries=len(crcs), module_layout_crc=hex(crcs['module_layout']),
                exported_reference_crcs_match=True, namespace_imports_match=True,
                runtime_symbol_names_resolve_uniquely=True, undefined_symbols=len(undefined),
                private_prelink_references=sorted(name for name in undefined if name not in exports),
                kernel_release=release, module_loaded=False, flashed=False,
                complete_abi_proven=False, runtime_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('module', 'vmlinux', 'symvers', 'release-file', 'llvm-nm', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; preserve previous audit')
    result = audit(args.module, args.vmlinux, args.symvers,
                   args.release_file.read_text().strip(), args.llvm_nm)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
