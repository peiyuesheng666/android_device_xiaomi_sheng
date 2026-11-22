#!/usr/bin/env python3
"""Read-only ARM64 THP string references and jump tables; never sends commands."""
import argparse
import re
import struct
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('binary', type=Path)
p.add_argument('disassembly', type=Path)
p.add_argument('--match', default='report rate|report_rate|user_cmd|socket|thp_daemon_cmd_process')
p.add_argument('--table', nargs=4, metavar=('VA', 'BASE', 'COUNT', 'WIDTH'))
args = p.parse_args()
blob = args.binary.read_bytes()
assert blob[:6] == b'\x7fELF\x02\x01'
phoff = struct.unpack_from('<Q', blob, 32)[0]
phsize, phnum = struct.unpack_from('<HH', blob, 54)
segments = [struct.unpack_from('<IIQQQQQQ', blob, phoff+i*phsize) for i in range(phnum)]

def offset(va):
    for typ, _, off, addr, _, size, _, _ in segments:
        if typ == 1 and addr <= va < addr+size:
            return off+va-addr
    raise ValueError(hex(va))

def string(va):
    try:
        off = offset(va)
        end = blob.index(b'\x00', off)
        value = blob[off:end].decode('ascii')
        return value if value and all(c.isprintable() for c in value) else ''
    except (ValueError, UnicodeDecodeError):
        return ''

if args.table:
    va, base, count, width = [int(x, 0) for x in args.table]
    for i in range(count):
        v = int.from_bytes(blob[offset(va)+i*width:offset(va)+(i+1)*width], 'little')
        print(f'{i}: {base+v*4:#x}')
else:
    lines = args.disassembly.read_text().splitlines()
    pages = {}
    for i, line in enumerate(lines):
        adr = re.search(r'adrp\s+(x\d+), (0x[0-9a-f]+)', line)
        add = re.search(r'add\s+(x\d+), (x\d+), #(\d+)', line)
        if adr:
            pages[adr[1]] = (int(adr[2], 16), i)
        if add and add[2] in pages:
            page, at = pages[add[2]]
            if i-at > 15:
                continue
            va = page+int(add[3])
            s = string(va)
            if re.search(args.match, s, re.I):
                print(f'{line.strip()} => {va:#x} {s}')
