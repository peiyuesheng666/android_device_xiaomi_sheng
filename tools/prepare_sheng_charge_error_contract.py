#!/usr/bin/env python3
"""Preserve firmware write errors in the source-built battery power supply."""
import argparse
import hashlib
import json
from pathlib import Path


def transform(text):
    start = text.index('static int battery_psy_set_prop(')
    end = text.index('\nstatic int battery_psy_prop_is_writeable(', start)
    function = text[start:end]
    assert function.count('rc = battery_psy_set_fcc(') == 1
    assert function.count('\n\treturn 0;\n}') + function.count('\n\treturn rc;\n}') == 1
    replacement = function.replace('\n\treturn 0;\n}', '\n\treturn rc;\n}')
    return text[:start] + replacement + text[end:]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    path = args.source_root / 'soc/drivers/power/supply/qti_battery_charger.c'
    original = path.read_bytes()
    assert hashlib.sha256(original).hexdigest() in (
        'f36ce31fcf799c230e54ce5dda64fec46054f73ddc49cd08ab3f55b38c710243',
        '968e3af1ec92f467f764b9ab377e396bb0507de9666deaf80aba66a7e66f7825',
        # Same setter fix plus the validated sheng USB3 orientation provider.
        'ff3d6196888ab06a4677f5686ee54f54711e061c10e226de2492e81e48408ed9',
        # Same setter fix plus explicit live CC provider-owner readiness.
        '712af37a7c5de44ae0b12eb03f1d2c6af6641dd84d912131d7506a1b2bf11482',
    ), 'Unknown charging source revision; no changes made'
    updated = transform(original.decode()).encode()
    if args.check:
        assert original == updated, 'Charging write-error fix is missing'
    elif updated != original:
        path.write_bytes(updated)
    print(json.dumps(dict(changed=original != updated,
                         sha256=hashlib.sha256(updated).hexdigest())))
