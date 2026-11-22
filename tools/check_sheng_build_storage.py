#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fail before a sheng WSL build can modify staging or exhaust host C:."""
import argparse
import os
from pathlib import Path
import shutil

from prepare_sheng_stylus_swap import host_paths, windows_c_path

GIB = 1024**3


def check_path(value, root_dev, c_dev):
    path = Path(os.path.abspath(value))
    if path.is_relative_to('/mnt') and not path.is_relative_to('/mnt/c'):
        raise RuntimeError(f'Non-C build path: {path}')
    path = path.resolve()
    if path.is_relative_to('/mnt') and not path.is_relative_to('/mnt/c'):
        raise RuntimeError(f'Non-C resolved build path: {path}')
    existing = path
    while not existing.exists():
        existing = existing.parent
    intended_device = c_dev if path.is_relative_to('/mnt/c') else root_dev
    if existing.stat().st_dev != intended_device:
        raise RuntimeError(f'Build path is on an unverified mount: {path}')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--full', action='store_true')
    p.add_argument('paths', nargs='+')
    args = p.parse_args()
    try:
        windows_c_path(host_paths()['base_path'])
        c = Path('/mnt/c')
        root_dev, c_dev = Path('/').stat().st_dev, c.stat().st_dev
        if root_dev == c_dev or not c.is_mount():
            raise RuntimeError('C: mount is not separate from the native WSL filesystem')
        for path in args.paths:
            check_path(path, root_dev, c_dev)
        free = shutil.disk_usage(c).free
        floor = 20 if args.full else 2
        if free < floor * GIB:
            raise RuntimeError(f'C: has {free / GIB:.2f} GiB free; need at least {floor} GiB '
                               'before staging (not a guarantee of sufficient build space)')
    except (RuntimeError, OSError, ValueError) as exc:
        p.exit(1, f'Sheng build storage preflight: {exc}\n')
    print(f'Sheng build storage preflight: C: has {free / GIB:.2f} GiB free')


if __name__ == '__main__':
    main()
