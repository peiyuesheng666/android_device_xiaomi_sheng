#!/usr/bin/env python3
"""Package the device Recovery UI extension on the installed r54 baseline."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

DEVICE = Path(__file__).resolve().parents[1]
WORKSPACE = DEVICE.parents[2]
ROM = Path('/root/sheng-lineage/lineage-24.0')
HOST = ROM / 'out/host/linux-x86/bin'
REVIEW = WORKSPACE / 'reports/device/20261112-recovery-pen'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--revision', type=int, choices=(55, 56, 57, 58, 59), default=55)
revision = parser.parse_args().revision
base_name = 'r%d-package.json' % (revision - 1) if revision >= 56 else 'recovery-package-receipt.json'
BASE = json.loads((REVIEW / base_name).read_text())
BUILD = BASE['ui_build'] if revision >= 57 else json.loads((REVIEW / ('r%d-ui-build.json' % revision)).read_text())
LAYOUT = json.loads((WORKSPACE / 'artifacts/recovery-sheng-lineage-24.0-r13-native-source-fast-touch/recovery-build-result.json').read_text())
OUT = Path(tempfile.mkdtemp(prefix='recovery-r%d-package-' % revision, dir='/root/sheng-lineage'))
tags = {54: 'r54-firmware-path', 55: 'r55-menu-battery',
        56: 'r56-battery-events', 57: 'r57-parallel-modules',
        58: 'r58-late-oops-module', 59: 'r59-ordered-late-oops'}
tag = tags[revision]
DEST = WORKSPACE / ('artifacts/recovery-sheng-lineage-24.0-' + tag)
commands = []


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args, **kwargs):
    result = subprocess.run(list(map(str, args)), **kwargs)
    commands.append({'command': list(map(str, args)), 'returncode': result.returncode})
    (OUT / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
    result.check_returncode()
    return result


def unpack(image, parts, root):
    run([sys.executable, ROM / 'system/tools/mkbootimg/unpack_bootimg.py',
         '--boot_img', image, '--out', parts], stdout=subprocess.DEVNULL)
    root.mkdir()
    payload = parts / 'ramdisk'
    if payload.read_bytes().endswith(b'#BOOTCONFIG\n'):
        stripped = parts / 'ramdisk-without-bootconfig'
        run([HOST / 'initrd_bootconfig', 'detach', payload, stripped, parts / 'bootconfig'])
        payload = stripped
    raw = run(['zstd', '-dc', payload], capture_output=True).stdout
    run(['cpio', '-idmu', '--no-absolute-filenames'], cwd=root, input=raw,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def tree(root):
    entries = {}
    for path in root.rglob('*'):
        name = str(path.relative_to(root))
        mode = stat.S_IMODE(path.lstat().st_mode)
        if path.is_symlink():
            entries[name] = ['symlink', os.readlink(path), mode]
        elif path.is_file():
            entries[name] = ['file', sha(path), mode]
        elif path.is_dir():
            entries[name] = ['directory', mode]
        else:
            raise RuntimeError('Unexpected special file: ' + name)
    return entries


def flatten_modules(root):
    # A release-named directory takes the sequential path in the pinned init.
    # The flat directory enables its dependency-aware parallel loader. Keep a
    # symlink for tools using uname -r; init skips symlinks during its dir scan.
    modules = root / 'lib/modules'
    assert modules.resolve().is_relative_to(root.resolve()) and not modules.is_symlink()
    entries = list(modules.iterdir())
    assert len(entries) == 1 and entries[0].is_dir() and not entries[0].is_symlink()
    versioned = entries[0]
    assert versioned.resolve().is_relative_to(root.resolve())
    release = versioned.name
    files = sorted(versioned.iterdir())
    assert files and all(path.is_file() and not path.is_symlink() for path in files)
    contents = {path.name: sha(path) for path in files}
    assert {'modules.dep', 'modules.load.recovery', 'modules.alias', 'modules.softdep'} <= contents.keys()
    # These depmod inputs already use basenames. No dependency or binary
    # metadata is regenerated, and no kernel module is changed or removed.
    for line in (versioned / 'modules.dep').read_text().splitlines():
        owner, dependencies = line.split(':', 1)
        assert all('/' not in name and name in contents for name in [owner, *dependencies.split()])
    for name in (versioned / 'modules.load.recovery').read_text().splitlines():
        assert '/' not in name and name in contents, name
    for path in files:
        target = modules / path.name
        assert target.resolve().is_relative_to(root.resolve()) and not target.exists()
        path.rename(target)
    versioned.rmdir()
    versioned.symlink_to('.', target_is_directory=True)
    assert {name: sha(modules / name) for name in contents} == contents
    assert all(sha(versioned / name) == digest for name, digest in contents.items())
    return {'layout': 'flat-with-release-symlink', 'release': release,
            'files': contents, 'module_count': sum(name.endswith('.ko') for name in contents),
            'all_module_and_metadata_bytes_retained': True}


assert BASE['revision'] == revision - 1 and BASE['avb_verified']
assert sha(Path(BASE['image'])) == BASE['sha256']
assert BUILD['scoped_native_compile_and_no_undefined_link_passed']
assert sha(Path(BUILD['library'])) == BUILD['sha256']
for relative, digest in BUILD['sources'].items():
    assert sha(DEVICE / relative) == digest, relative
parts, root = OUT / 'parts', OUT / 'root'
unpack(BASE['image'], parts, root)
before = tree(root)
for name, digest in BUILD['linked_installed_dependencies'].items():
    assert sha(root / 'system/lib64' / name) == digest
shutil.copyfile(BUILD['library'], root / 'system/lib64/librecovery_ui_ext.so')
startup_sources = {}
module_layout = None
if revision >= 56:
    for relative, embedded in {
        'rootdir/recovery/init.recovery.sheng.rc': 'init.recovery.qcom.rc',
        'rootdir/recovery/hardware.sh': 'system/bin/sheng-recovery-hardware',
    }.items():
        shutil.copyfile(DEVICE / relative, root / embedded)
        startup_sources[relative] = sha(DEVICE / relative)
    for relative in ('rootdir/recovery/bootconfig', 'rootdir/recovery/standalone.json'):
        startup_sources[relative] = sha(DEVICE / relative)
if revision == 57:
    standalone = json.loads((DEVICE / 'rootdir/recovery/standalone.json').read_text())
    assert standalone['module_layout'] == 'flat-with-release-symlink'
    module_layout = flatten_modules(root)
elif revision >= 58:
    module_layout = BASE['module_layout']
    modules = root / 'lib/modules'
    assert module_layout['layout'] == 'flat-with-release-symlink'
    assert {name: sha(modules / name) for name in module_layout['files']} == module_layout['files']
    standalone = json.loads((DEVICE / 'rootdir/recovery/standalone.json').read_text())
    late = standalone['deferred_recovery_modules']
    assert late == ['block2mtd.ko']
    original_load = (modules / 'modules.load.recovery').read_text().splitlines()
    source_load = DEVICE / 'configs/modules/modules.load.recovery'
    new_load = source_load.read_text().splitlines()
    assert new_load == [name for name in original_load if name not in late]
    dependencies = {line.split(':', 1)[0]: line.split(':', 1)[1].split()
                    for line in (modules / 'modules.dep').read_text().splitlines()}
    assert all(name not in deps for deps in dependencies.values() for name in late)
    assert all(dep in new_load for name in late for dep in dependencies[name])
    (modules / 'modules.load.recovery').write_text('\n'.join(new_load) + '\n')
    module_layout['files']['modules.load.recovery'] = sha(modules / 'modules.load.recovery')
    module_layout['late_modules'] = late
    module_layout['changed_metadata'] = ['modules.load.recovery']
    module_layout['all_module_and_metadata_bytes_retained'] = False
    module_layout['all_module_bytes_retained'] = True
    startup_sources['configs/modules/modules.load.recovery'] = sha(source_load)
    for relative, embedded in {
        'rootdir/recovery/init.recovery.sheng-late-modules.rc': 'system/etc/init/init.recovery.sheng-late-modules.rc',
        'rootdir/recovery/late-modules.sh': 'system/bin/sheng-recovery-late-modules',
    }.items():
        shutil.copyfile(DEVICE / relative, root / embedded)
        os.chmod(root / embedded, 0o644 if embedded.endswith('.rc') else 0o755)
        startup_sources[relative] = sha(DEVICE / relative)
after = tree(root)
changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
expected_changes = ['system/lib64/librecovery_ui_ext.so']
if revision == 56:
    expected_changes += ['init.recovery.qcom.rc', 'system/bin/sheng-recovery-hardware']
elif revision == 57:
    # r57 reuses the exact r56 UI and startup files; only module paths change.
    expected_changes = ['lib/modules/' + module_layout['release']]
    for name in module_layout['files']:
        expected_changes += ['lib/modules/' + name,
                             'lib/modules/' + module_layout['release'] + '/' + name]
elif revision == 58:
    expected_changes = ['lib/modules/modules.load.recovery',
                        'system/etc/init/init.recovery.sheng-late-modules.rc',
                        'system/bin/sheng-recovery-late-modules']
elif revision == 59:
    expected_changes = []
assert changed == sorted(expected_changes), changed

cpio, ramdisk = OUT / 'ramdisk.cpio', OUT / 'ramdisk.zst'
with cpio.open('wb') as output:
    run([HOST / 'mkbootfs', '-d', ROM / 'out/target/product/sheng', root], stdout=output)
run(['zstd', '-q', '-19', '-T4', '-f', cpio, '-o', ramdisk])
if revision >= 56:
    attached = OUT / 'ramdisk-with-bootconfig'
    run([HOST / 'initrd_bootconfig', 'attach', '--output', attached, ramdisk,
         DEVICE / 'rootdir/recovery/bootconfig'])
    ramdisk = attached
config = LAYOUT['boot_layout']
image = OUT / 'recovery.img'
old_tag = tags[revision - 1]
cmdline = BASE['cmdline'].replace('sheng_recovery_test=' + old_tag,
                                 'sheng_recovery_test=' + tag)
if revision == 56:
    cmdline = cmdline.replace('androidboot.load_modules_parallel=false', 'bootconfig')
if revision >= 56:
    assert cmdline.split().count('bootconfig') == 1
args = [sys.executable, ROM / 'system/tools/mkbootimg/mkbootimg.py']
for flag, value in {
    'header_version': 2, 'pagesize': config['page_size'], 'base': config['base'],
    'kernel_offset': config['kernel_offset'], 'ramdisk_offset': config['ramdisk_offset'],
    'tags_offset': config['tags_offset'], 'dtb_offset': config['dtb_offset'],
    'second_offset': 0, 'os_version': config['recovery_os_version'],
    'os_patch_level': config['recovery_os_patch_level'], 'kernel': parts / 'kernel',
    'ramdisk': ramdisk, 'dtb': parts / 'dtb', 'recovery_dtbo': parts / 'recovery_dtbo',
    'cmdline': cmdline, 'output': image,
}.items():
    args.extend(['--' + flag, value])
run(args)
run([HOST / 'avbtool', 'add_hash_footer', '--image', image, '--partition_name', 'recovery',
     '--partition_size', config['partition_size'], '--algorithm', 'SHA256_RSA4096',
     '--key', ROM / 'external/avb/test/data/testkey_rsa4096.pem'])
run([HOST / 'avbtool', 'verify_image', '--image', image])
check_parts, check_root = OUT / 'verified', OUT / 'verified-root'
unpack(image, check_parts, check_root)
assert tree(check_root) == after
bootconfig_padding = 0
if revision >= 56:
    expected_bootconfig = (DEVICE / 'rootdir/recovery/bootconfig').read_bytes()
    embedded_bootconfig = (check_parts / 'bootconfig').read_bytes()
    assert embedded_bootconfig.startswith(expected_bootconfig)
    padding = embedded_bootconfig[len(expected_bootconfig):]
    # initrd_bootconfig aligns the trailer to four bytes with up to three
    # NULs. The padding depends on the compressed ramdisk size.
    assert len(padding) <= 3 and padding == b'\0' * len(padding)
    bootconfig_padding = len(padding)
for name in ('kernel', 'dtb', 'recovery_dtbo'):
    assert sha(parts / name) == sha(check_parts / name)
assert image.stat().st_size == 104857600
DEST.mkdir(exist_ok=False)
target = DEST / ('lineage-24.0-sheng-recovery-' + tag + '.img')
shutil.copyfile(image, target)
receipt = {
    'revision': revision, 'baseline_revision': revision - 1, 'image': str(target),
    'sha256': sha(target), 'bytes': target.stat().st_size,
    'base_image_sha256': BASE['sha256'], 'changed_ramdisk_files': changed,
    'all_other_files_and_modes_unchanged': True, 'kernel_dtb_dtbo_unchanged': True,
    'r54_policy_retained': True, 'startup_sources': startup_sources,
    'bootconfig_attached_and_verified': revision >= 56,
    'bootconfig_alignment_padding_bytes': bootconfig_padding,
    'module_layout': module_layout, 'r56_ui_reused_unchanged': revision >= 57,
    'packaging_source_sha256': sha(Path(__file__)),
    'avb_verified': True, 'embedded_readback_verified': True,
    'ui_build': BUILD, 'cmdline': cmdline, 'work': str(OUT),
    'full_product_build_passed': False, 'normal_soong_module_build_passed': False,
    'installed': False, 'hardware_boot_tested': False,
}
for path in (DEST / 'build-receipt.json', REVIEW / ('r%d-package.json' % revision)):
    path.write_text(json.dumps(receipt, indent=2) + '\n')
(DEST / 'SHA256SUMS').write_text(sha(target) + '  ' + target.name + '\n')
print(json.dumps({key: receipt[key] for key in
    ('revision', 'image', 'sha256', 'bytes', 'avb_verified', 'embedded_readback_verified')}))
print('Changed ramdisk entries:', len(changed))
if module_layout:
    print('Unchanged kernel modules:', module_layout['module_count'])
