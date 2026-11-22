"""Read-only storage preflight for isolated diagnostic builds.

The current WSL VHD lives on C:. Ext4 free space does not establish that
the Windows host has room to grow that VHD. Never clean user files here.
"""
from pathlib import Path
import os
import shutil

GIB = 1024 ** 3


def existing_ancestor(path):
    path = Path(path).resolve()
    while not path.exists():
        parent = path.parent
        if parent == path:
            raise RuntimeError(f'Cannot determine output filesystem: {path}')
        path = parent
    return path


def require_build_space(output, *, host_volume=None,
                        minimum_output=2 * GIB, minimum_host=GIB):
    checks = [(existing_ancestor(output), minimum_output, 'output filesystem')]
    if host_volume is None:
        if os.name == 'nt':
            host_volume = Path('C:/')
        elif Path('/mnt/c').is_dir():
            host_volume = Path('/mnt/c')
    if host_volume is not None:
        checks.append((Path(host_volume), minimum_host, 'Windows host volume'))
    results = []
    for path, minimum, label in checks:
        if minimum <= 0:
            raise ValueError('Storage headroom must be positive')
        free = shutil.disk_usage(path).free
        results.append(dict(path=str(path), free_bytes=free, minimum_bytes=minimum))
        if free < minimum:
            raise RuntimeError(f'Build not started: {label} {path} has {free} bytes free; '
                               f'needs at least {minimum}. Resolve storage exhaustion '
                               'before retrying; no automatic cleanup is performed.')
    return results
