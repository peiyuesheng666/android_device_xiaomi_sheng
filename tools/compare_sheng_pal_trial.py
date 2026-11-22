#!/usr/bin/env python3
"""Compare PAL ELF dynamic surface only; not full C++ ABI or device acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def inspect(path):
    def read(*flags):
        return subprocess.check_output(['readelf', *flags, str(path)], text=True)
    header = read('-h')
    symbols = read('--dyn-syms', '--wide')
    defined, undefined = set(), set()
    for line in symbols.splitlines():
        fields = line.split()
        if len(fields) < 8 or not fields[0].endswith(':'):
            continue
        if fields[4] not in ('GLOBAL', 'WEAK'):
            continue
        # Preserve version suffixes, but omit display-only version indices.
        signature = (fields[7], fields[3], fields[4], fields[5])
        (undefined if fields[6] == 'UND' else defined).add(signature)
    return {
        'path': str(path), 'bytes': path.stat().st_size,
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'machine': re.search(r'Machine:\s*(.+)', header).group(1),
        'class': re.search(r'Class:\s*(.+)', header).group(1),
        'needed': sorted(re.findall(r'\(NEEDED\).*?\[(.*?)\]', read('-d'))),
        'defined': defined, 'undefined': undefined,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('runtime', type=Path)
    p.add_argument('candidate', type=Path)
    args = p.parse_args()
    old, new = inspect(args.runtime), inspect(args.candidate)
    removed = sorted(old['defined'] - new['defined'])
    new_undefined = sorted(new['undefined'] - old['undefined'])
    needed_equal = old['needed'] == new['needed']
    machine_equal = old['machine'] == new['machine'] == 'AArch64'
    class_equal = old['class'] == new['class'] == 'ELF64'
    for item in (old, new):
        item['defined_count'] = len(item.pop('defined'))
        item['undefined_count'] = len(item.pop('undefined'))
    result = {
        'scope': 'ELF dynamic surface only; no object-layout, semantic or DSP proof',
        'runtime': old, 'candidate': new,
        'removed_exports': removed, 'new_undefined': new_undefined,
        'needed_equal': needed_equal, 'machine_equal': machine_equal,
        'class_equal': class_equal,
        'surface_check_passed': not removed and not new_undefined and needed_equal
                                and machine_equal and class_equal,
        'runtime_verified': False,
    }
    print(json.dumps(result, indent=2))
    return 0 if result['surface_check_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
