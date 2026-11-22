#!/usr/bin/env python3
"""Reproduce a hidden init bind mount in a private Linux mount namespace.

Host-only mechanics test. Does not reproduce Android's pre-policy SELinux state,
flash, access ADB, modify Android sources, or mount anything in the caller namespace.
Run as root under Linux/WSL. All test mounts disappear with the child namespace.
"""
import argparse
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def run(*argv):
    subprocess.run(list(map(str, argv)), check=True, capture_output=True, timeout=15)


def check_fstab(path):
    rows = [line.split() for line in path.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith('#')]
    system = [row for row in rows if len(row) >= 5 and row[1] == '/system']
    assert sorted(row[2] for row in system) == ['erofs', 'ext4']
    for row in system:
        flags = set(row[4].split(','))
        assert row[0] == 'system' and {'wait', 'slotselect', 'avb=vbmeta_system',
                                     'logical', 'first_stage_mount'} <= flags
        assert not any(flag.startswith('overlay=') for flag in flags)
    return dict(system_filesystems=sorted(row[2] for row in system),
                all_system_first_stage_alternatives_allow_normal_overlay=True,
                system_avb_flags_retained=True)


def child(root, caller_namespace):
    namespace = os.readlink('/proc/self/ns/mnt')
    assert namespace != caller_namespace, 'Refuse to mount in the caller namespace'
    root = Path(root).resolve(strict=True)
    assert root.parent == Path('/tmp') and root.name.startswith('sheng-magisk-overlay-')
    assert not any(field.startswith(('shared:', 'master:'))
                   for row in Path('/proc/self/mountinfo').read_text().splitlines()
                   for field in (row.split()[6:row.split().index('-')] if row.split()[4] == '/' else []))
    run('mount', '-t', 'tmpfs', '-o', 'size=8m', 'sheng-handoff-test', root)
    system = root/'system'
    (system/'bin').mkdir(parents=True)
    (root/'upper').mkdir()
    (root/'work').mkdir()
    target = system/'bin/init'
    target.write_text('ANDROID_INIT\n')
    source = root/'sdcard'
    source.write_text('MAGISK_INIT\n')
    before_inode = target.stat().st_ino
    run('mount', '--bind', source, target)
    source.unlink()
    bound = target.read_text()
    bound_inode = target.stat().st_ino
    assert bound == 'MAGISK_INIT\n' and bound_inode != before_inode
    try:
        os.getxattr(target, 'security.selinux')
        label_errno = None
    except OSError as error:
        label_errno = error.errno
    bind_before = [l for l in Path('/proc/self/mountinfo').read_text().splitlines()
                   if l.split()[4] == str(target)]
    assert len(bind_before) == 1
    run('mount', '-t', 'overlay', 'overlay', '-o',
        f'lowerdir={system},upperdir={root}/upper,workdir={root}/work,userxattr', system)
    visible = target.read_text()
    rows = Path('/proc/self/mountinfo').read_text().splitlines()
    hidden_bind = [l for l in rows if l.split()[4] == str(target)]
    overlay = [l for l in rows if l.split()[4] == str(system) and ' - overlay ' in l]
    assert visible == 'ANDROID_INIT\n', 'Parent overlay did not hide the child bind'
    assert hidden_bind == bind_before and len(overlay) == 1
    run('umount', system)
    restored = target.read_text()
    assert restored == 'MAGISK_INIT\n'
    return dict(passed=True, host_kernel=os.uname().release,
                caller_mount_namespace=caller_namespace, child_mount_namespace=namespace,
                visible_before_overlay=bound.strip(), visible_after_overlay=visible.strip(),
                visible_after_overlay_unmount=restored.strip(),
                child_bind_remains_in_mountinfo=True,
                unlabeled_host_tmpfs_security_selinux_errno=label_errno,
                host_xattr_is_enodata=label_errno == errno.ENODATA,
                android_prepolicy_selinux_reproduced=False,
                current_android_kernel_defect_proven=False,
                mounts_only_in_private_child_namespace=True,
                tablet_access=False, flash=False, reboot=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--child', nargs=2, metavar=('ROOT', 'CALLER_NAMESPACE'),
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    assert sys.platform == 'linux' and os.geteuid() == 0
    if args.child:
        print(json.dumps(child(*args.child)))
        return
    output = args.out.resolve() if args.out else None
    assert output is None or not output.exists(), 'Do not overwrite an earlier result'
    namespace = os.readlink('/proc/self/ns/mnt')
    mounts_before = Path('/proc/self/mountinfo').read_bytes()
    fstab = check_fstab(Path(__file__).resolve().parents[1]/'rootdir/etc/fstab.qcom')
    with tempfile.TemporaryDirectory(prefix='sheng-magisk-overlay-', dir='/tmp') as root:
        process = subprocess.run(['unshare', '--mount', '--propagation', 'private',
                                  sys.executable, str(Path(__file__).resolve()),
                                  '--child', root, namespace], capture_output=True,
                                 text=True, timeout=60)
        assert process.returncode == 0, process.stderr
        result = json.loads(process.stdout)
        assert not list(Path(root).iterdir()), 'Test mount leaked into caller'
    assert namespace == os.readlink('/proc/self/ns/mnt')
    assert Path('/proc/self/mountinfo').read_bytes() == mounts_before, 'Caller mounts changed'
    result['caller_mount_table_unchanged'] = True
    result['device_fstab_contract'] = fstab
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
