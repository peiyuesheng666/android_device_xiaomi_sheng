#!/usr/bin/env python3
"""Back up validated super extents without mapping, mounting or device writes.

This captures PHYSICAL BACKING, not a snapshot-composed logical device. A COW
partition or updated attribute must not be interpreted as merged/boot-ready.
No backup produced by this tool authorizes a raw super write.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

from storage_guard import require_build_space

SERIAL = 'ca10ede3'
LPDUMP = '/root/sheng-pixelos/android/out-clean-ota-20261116/host/linux-x86/bin/lpdump'
SIZES = {
    'system_b': 893321216,
    'system_ext_b': 504053760,
    'product_b': 5305776 * 512,
    'odm_b': 2228776 * 512,
    'vendor_b': 725768 * 512,
    'vendor_dlkm_b': 81760 * 512,
    'system_dlkm_b': 792 * 512,
}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read_command(extent):
    # adb exec-out may merge remote stderr into the binary stdout stream.
    # Suppress dd statistics remotely, not merely in the host subprocess.
    return ('dd if=/dev/block/by-name/super bs=1048576 '
            'iflag=skip_bytes,count_bytes '
            f'skip={extent["offset"]} count={extent["bytes"]} 2>/dev/null')


def extents_for(layout, name, super_bytes, expected_bytes):
    if name not in SIZES or super_bytes <= 0 or expected_bytes <= 0:
        raise ValueError('Unsupported partition or invalid size')
    matches = re.findall(r'^  Name: ' + re.escape(name) + r'\n(.*?)(?=^------------------------)',
                         layout, re.M | re.S)
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous partition')
    block = matches[0]
    if block.count('  Extents:\n') != 1:
        raise ValueError('Missing or ambiguous extent list')
    attributes = re.findall(r'^  Attributes: (.*)$', block, re.M)
    if len(attributes) != 1:
        raise ValueError('Missing or ambiguous attributes')
    rows = block.split('  Extents:\n', 1)[1].splitlines()
    result, end = [], 0
    physical = []
    for row in rows:
        if not row.strip():
            continue
        match = re.fullmatch(r'    (\d+) \.\. (\d+) linear super (\d+)', row)
        if not match:
            raise ValueError('Unknown or non-linear extent')
        first, last, sector = map(int, match.groups())
        start, count = sector * 512, (last - first + 1) * 512
        if first * 512 != end or last < first or sector < 2048 or start + count > super_bytes:
            raise ValueError('Non-contiguous logical or out-of-bounds physical extent')
        if any(start < b and a < start + count for a, b in physical):
            raise ValueError('Overlapping physical extents')
        physical.append((start, start + count))
        result.append({'offset': start, 'bytes': count})
        end += count
    if not result or end != expected_bytes:
        raise ValueError('Unexpected partition size')
    return result, attributes[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--partition', choices=tuple(SIZES), action='append', required=True)
    args = parser.parse_args()
    if len(set(args.partition)) != len(args.partition):
        parser.error('Duplicate partitions')
    adb = args.adb.resolve(strict=True)
    out = args.output.resolve()
    if out.exists():
        parser.error('Output must be new; preserve earlier evidence')
    storage = require_build_space(out, minimum_output=sum(SIZES[n] for n in args.partition) + 1024**3)
    out.mkdir(parents=True)
    prefix = [str(adb), '-s', SERIAL]

    def shell(command, timeout=120):
        return subprocess.check_output(prefix + ['shell', 'sh -s'],
                                       input='set -eu\n' + command + '\n', text=True,
                                       encoding='utf-8', timeout=timeout).strip()

    def identity():
        return shell('getprop ro.serialno; getprop ro.product.device; '
                     'getprop ro.boot.slot_suffix; getprop init.svc.recovery; '
                     'id -u; cat /proc/sys/kernel/random/boot_id').splitlines()

    before = identity()
    if len(before) != 6 or before[:5] != [SERIAL, 'sheng', '_b', 'running', '0']:
        raise RuntimeError('Requires the identified root Recovery in slot b')

    def metadata():
        data = subprocess.check_output(prefix + ['exec-out',
            'dd if=/dev/block/by-name/super bs=1048576 count=1 2>/dev/null'], timeout=30)
        if len(data) != 1024**2:
            raise RuntimeError('Short metadata capture')
        return data

    original_metadata = metadata()
    meta = out / 'super-metadata.bin'
    meta.write_bytes(original_metadata)
    path = meta.as_posix()
    if not re.match(r'^[A-Za-z]:/', path):
        raise RuntimeError('Run this host helper on Windows')
    linux_path = '/mnt/' + path[0].lower() + '/' + path[3:]
    process = subprocess.run(['wsl', '-d', 'Ubuntu-22.04', '--exec', LPDUMP,
                              '--slot=1', linux_path], capture_output=True, timeout=60)
    (out / 'lpdump.txt').write_bytes(process.stdout)
    (out / 'lpdump.stderr').write_bytes(process.stderr)
    process.check_returncode()
    layout = process.stdout.decode('utf-8').replace('\r\n', '\n')
    size = int(shell('blockdev --getsize64 /dev/block/by-name/super'))
    plans = {name: extents_for(layout, name, size, SIZES[name]) for name in args.partition}
    results = {}
    for name, (extents, attributes) in plans.items():
        target = out / (name + '.physical-backing.img.partial')
        commands = []
        with target.open('xb') as stream:
            for extent in extents:
                command = read_command(extent)
                start = stream.tell()
                process = subprocess.run(prefix + ['exec-out', command], stdout=stream,
                                         stderr=subprocess.PIPE, timeout=180)
                with (out / (name + '-dd.stderr')).open('ab') as log:
                    log.write(process.stderr)
                process.check_returncode()
                if stream.tell() - start != extent['bytes']:
                    raise RuntimeError('Short or oversized extent read; retain partial evidence')
                commands.append(command + ' || exit 1')
        host_hash = digest(target)
        device_hash = shell('{ ' + '; '.join(commands) + '; } | sha256sum', timeout=240).split()[0]
        if host_hash != device_hash or target.stat().st_size != SIZES[name]:
            raise RuntimeError('Physical backing readback mismatch')
        if identity() != before or metadata() != original_metadata:
            raise RuntimeError('Boot/mode/slot or metadata changed during backup')
        complete = target.with_suffix('')
        target.rename(complete)
        results[name] = dict(path=str(complete), bytes=SIZES[name], sha256=host_hash,
                             device_sha256=device_hash, extents=extents, attributes=attributes,
                             cow_partition_present=('  Name: ' + name + '-cow\n') in layout)
    result = dict(passed=True, serial=SERIAL, slot='_b', boot_id=before[-1], storage=storage,
                  metadata_sha256=hashlib.sha256(original_metadata).hexdigest(),
                  metadata_unchanged=True, partitions=results,
                  physical_backing_only=True, snapshot_composed_view_verified=False,
                  device_partition_writes=False, device_mapper_changes=False,
                  device_mount_changes=False, raw_super_write_authorized=False)
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
