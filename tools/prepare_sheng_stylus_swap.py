#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify C-only build swap; create a native file only with an explicit size."""
import argparse
import configparser
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import stat
import subprocess

NATIVE_SWAP = Path('/root/sheng-build.swap')
ALLOWED_FILES = (
    NATIVE_SWAP,
    Path('/root/sheng-lineage/lineage-build.swap'),
    Path('/root/sheng-lineage/lineage-extra.swap'),
)


def windows_c_path(value):
    # Registry BasePath may use the extended-length Windows path prefix.
    value = value.removeprefix('\\\\?\\')
    path = PureWindowsPath(value)
    if path.drive.upper() != 'C:' or '..' in path.parts:
        raise RuntimeError('Build swap and its host configuration must be on C:')
    return Path('/mnt/c', *path.parts[1:])


def host_paths():
    if os.environ.get('WSL_DISTRO_NAME') != 'Ubuntu-22.04':
        raise RuntimeError('Unexpected WSL distribution for the C-only build swap')
    command = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$taskDistributions = @(Get-ChildItem -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' |
    Get-ItemProperty | Where-Object DistributionName -eq 'Ubuntu-22.04')
if ($taskDistributions.Count -ne 1) { throw 'WSL distribution identity is ambiguous' }
[ordered]@{
    distribution = $taskDistributions[0].DistributionName
    base_path = $taskDistributions[0].BasePath
    config_path = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.wslconfig'
} | ConvertTo-Json -Compress
"""
    output = subprocess.check_output([
        '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe',
        '-NoProfile', '-NonInteractive', '-Command', command,
    ], text=True, encoding='utf-8', timeout=30)
    result = json.loads(output)
    if result['distribution'] != 'Ubuntu-22.04':
        raise RuntimeError('Unexpected registered WSL distribution')
    return result


def swaps():
    result = []
    for line in Path('/proc/swaps').read_text().splitlines()[1:]:
        name, kind, size, used, priority = line.split()
        result.append(dict(name=name, kind=kind, bytes=int(size)*1024,
                           used_bytes=int(used)*1024, priority=int(priority)))
    return result


def verify_active(entries):
    allowed = {str(path) for path in ALLOWED_FILES}
    if any(entry['kind'] != 'file' or entry['name'] not in allowed for entry in entries):
        raise RuntimeError('C-only policy rejects an active default disk or unverified swap file; '
                           'stop the build and restart idle WSL with swap=0')


def create_native_swap(gib):
    path = NATIVE_SWAP
    if path.parent.resolve() != Path('/root') or path.parent.stat().st_dev != Path('/').stat().st_dev:
        raise RuntimeError('Build swap must stay in the native root filesystem')
    mount = json.loads(subprocess.check_output([
        'findmnt', '--json', '--target', str(path.parent), '--output', 'TARGET,FSTYPE',
    ], text=True))['filesystems']
    if len(mount) != 1 or mount[0] != {'target': '/', 'fstype': 'ext4'}:
        raise RuntimeError('Build swap parent must be on the C-backed ext4 root')
    lock_path = Path('/root/.sheng-build-swap.lock')
    if lock_path.is_symlink():
        raise RuntimeError('Swap creation lock must not be a symlink')
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists() or path.is_symlink():
            return False
        size = gib * 1024**3
        if shutil.disk_usage('/mnt/c').free < size + 20 * 1024**3:
            raise RuntimeError('Not enough free C: space to reserve build swap')
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        inode = os.fstat(descriptor).st_ino
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                os.posix_fallocate(stream.fileno(), 0, size)
                os.fsync(stream.fileno())
            subprocess.run(['/sbin/mkswap', str(path)], check=True, capture_output=True)
        except BaseException:
            # Remove only this newly allocated, inactive file after a failure.
            if path.is_file() and not path.is_symlink() and path.stat().st_ino == inode:
                path.unlink()
            raise
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--create-gib', type=int, default=0,
                        help='Create C-backed build swap only if no allowed file remains; 0 disables creation')
    args = parser.parse_args()
    if not 0 <= args.create_gib <= 64:
        parser.error('--create-gib must be between 0 and 64')
    work = args.work.resolve(strict=True)
    receipt_path = work/'swap-priority.json'
    if receipt_path.exists():
        raise RuntimeError('Swap policy receipt would be overwritten')
    paths = host_paths()
    config_path = windows_c_path(paths['config_path'])
    distro_path = windows_c_path(paths['base_path'])
    disk_path = distro_path/'ext4.vhdx'
    if not disk_path.is_file() or disk_path.is_symlink():
        raise RuntimeError('The registered C: distribution backing file is unavailable')
    config_bytes = config_path.read_bytes()
    config = configparser.ConfigParser()
    config.read_string(config_bytes.decode('utf-8-sig'))
    if config.get('wsl2', 'swap', fallback='').upper() not in ('0', '0MB', '0GB'):
        raise RuntimeError('C-only build swap requires automatic WSL swap to be disabled (swap=0)')
    configured_file = config.get('wsl2', 'swapFile', fallback='')
    if configured_file:
        windows_c_path(configured_file)
    processes = subprocess.check_output(['ps', '-eo', 'comm='], text=True).splitlines()
    if any(name.strip() in ('soong_build', 'ninja') for name in processes):
        raise RuntimeError('Do not change swap during another build')
    before = swaps()
    verify_active(before)
    created = False
    if args.create_gib and not any(path.exists() or path.is_symlink() for path in ALLOWED_FILES):
        created = create_native_swap(args.create_gib)
    files = []
    for path in ALLOWED_FILES:
        if not path.exists():
            continue
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or path.resolve() != path:
            raise RuntimeError('Swap must be an existing regular file with no symlink components')
        mount = json.loads(subprocess.check_output([
            'findmnt', '--json', '--target', str(path), '--output', 'SOURCE,TARGET,FSTYPE',
        ], text=True))['filesystems']
        if (len(mount) != 1 or mount[0]['target'] != '/' or mount[0]['fstype'] != 'ext4'
                or metadata.st_dev != Path('/').stat().st_dev):
            raise RuntimeError('Swap file is outside the registered C-backed root filesystem')
        files.append(dict(path=str(path), size_bytes=metadata.st_size,
                          allocated_bytes=metadata.st_blocks*512, mount=mount[0]))
    if not files:
        raise RuntimeError('No existing C-backed build swap file is available')
    receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), complete=False,
                   policy='C-only', configuration_sha256=hashlib.sha256(config_bytes).hexdigest(),
                   configured_backing_file=None, default_wsl_swap_disabled=True,
                   distro_host_backing_file=str(disk_path), before=before, files=files,
                   creates_or_resizes_swap=created,
                   created_file=str(NATIVE_SWAP) if created else None,
                   persistent_configuration_changed=False,
                   e_drive_swap_allowed=False)
    receipt_path.write_text(json.dumps(receipt, indent=2)+'\n')
    try:
        active = {entry['name'] for entry in before}
        for entry in files:
            if entry['path'] not in active:
                subprocess.run(['/sbin/swapon', '--priority', '0', entry['path']], check=True)
        after = swaps()
        verify_active(after)
        if {entry['name'] for entry in after} != {entry['path'] for entry in files}:
            raise RuntimeError('C-backed swap readback failed')
        if config_path.read_bytes() != config_bytes:
            raise RuntimeError('WSL configuration changed during swap preparation')
        receipt.update(complete=True, after=after,
                       total_swap_bytes=sum(entry['bytes'] for entry in after))
    except BaseException as error:
        receipt['error'] = repr(error)
        raise
    finally:
        receipt_path.write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
