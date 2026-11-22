#!/usr/bin/env python3
"""Compare sheng live lower partition data and stored hash trees to AVB readbacks."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


class SequentialImage:
    def __init__(self, pipe):
        self.pipe = pipe
        self.position = 0

    def seek(self, offset):
        if offset != self.position:
            raise ValueError(f'Nonsequential read: {self.position} -> {offset}')

    def read(self, count):
        data = self.pipe.read(count)
        if len(data) != count:
            raise EOFError(f'Short stream at {self.position}: {len(data)}/{count}')
        self.position += count
        return data


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('avbtool', type=Path)
    p.add_argument('adb', type=Path)
    p.add_argument('readbacks', type=Path)
    p.add_argument('partitions', nargs='+', choices=['vendor', 'odm', 'system_dlkm',
                   'vendor_dlkm', 'product', 'system', 'system_ext'])
    args = p.parse_args()
    sys.path.insert(0, str(args.avbtool.resolve().parent))
    import avbtool as a
    adb = [str(args.adb.resolve()), '-s', 'ca10ede3', 'exec-out']

    def text(command):
        return subprocess.check_output(adb + [command], text=True, timeout=30).strip()

    def identity():
        return text('getprop ro.product.device; getprop ro.boot.slot_suffix; '
                    'cat /proc/sys/kernel/random/boot_id').splitlines()

    boot = identity()
    if len(boot) != 3 or boot[:2] != ['sheng', '_b']:
        raise ValueError(f'Unexpected device: {boot}')
    descriptors = {}
    for name in ('vbmeta_b', 'vbmeta_system_b'):
        path = args.readbacks / (name + '.img')
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
        actual = text(f"su -c 'sha256sum /dev/block/by-name/{name}'").split()[0]
        if actual != expected:
            raise ValueError(f'{name}: live digest differs from readback')
        _, _, entries, _ = a.Avb()._parse_image(a.ImageHandler(str(path), read_only=True))
        for d in entries:
            if isinstance(d, a.AvbHashtreeDescriptor):
                if d.partition_name in descriptors:
                    raise ValueError(f'Duplicate descriptor: {d.partition_name}')
                descriptors[d.partition_name] = d

    mismatches = False
    for name in args.partitions:
        d = descriptors[name]
        block = d.data_block_size
        end = d.tree_offset + d.tree_size
        if (not d.root_digest or block != d.hash_block_size or block != 4096
                or d.tree_offset != d.image_size or end % block or not d.tree_size):
            raise ValueError(f'{name}: unsupported descriptor geometry')
        digest = d._hashtree_digest_size()
        padding = a.round_to_pow2(digest) - digest
        offsets, size = a.calc_hash_level_offsets(d.image_size, block, digest + padding)
        if size != d.tree_size:
            raise ValueError(f'{name}: inconsistent computed tree size')
        dev = f'/dev/block/mapper/{name}_b'
        if int(text(f"su -c 'blockdev --getsize64 {dev}'")) < end:
            raise ValueError(f'{name}: device smaller than descriptor span')
        command = f"su -c 'dd if={dev} bs=4096 count={end // block} status=none'"
        with subprocess.Popen(adb + [command], stdout=subprocess.PIPE) as proc:
            try:
                stream = SequentialImage(proc.stdout)
                root, tree = a.generate_hash_tree(stream, d.image_size, block,
                    d.hash_algorithm, d.salt, padding, offsets, size)
                stored_matches = tree == stream.read(d.tree_size)
                if proc.stdout.read(1) or proc.wait(timeout=20) != 0:
                    raise OSError(f'{name}: unexpected stream length or adb error')
            finally:
                if proc.poll() is None:
                    proc.kill()
        if identity() != boot:
            raise ValueError('Device identity changed during verification')
        root_matches = root == d.root_digest
        mismatches |= not (root_matches and stored_matches)
        print(json.dumps(dict(partition=name, boot_id=boot[2], bytes=end,
                              signed_root_matches=root_matches,
                              stored_tree_matches=stored_matches)), flush=True)
    return int(mismatches)


if __name__ == '__main__':
    sys.exit(main())
