#!/usr/bin/env python3
"""Repack verified r13 with only the compiled policy and board startup script."""
from pathlib import Path
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
HOST = ROM/'out/host/linux-x86/bin'
BASE_DIR = WORKSPACE/'artifacts/recovery-sheng-lineage-24.0-r13-native-source-fast-touch'
DEST = WORKSPACE/'artifacts/recovery-sheng-lineage-24.0-r54-firmware-path'
WORK = Path(tempfile.mkdtemp(prefix='recovery-r54-package-', dir='/root/sheng-lineage'))
REVIEW = WORKSPACE/'reports/device/20261112-recovery-pen'
base = json.loads((BASE_DIR/'recovery-build-result.json').read_text())
compiled = json.loads((REVIEW/'policy-build-receipt.json').read_text())
commands = []

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def run(args, **kwargs):
    result = subprocess.run(list(map(str, args)), **kwargs)
    commands.append({'command': list(map(str, args)), 'returncode': result.returncode})
    (WORK/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
    if result.returncode:
        raise RuntimeError('Failed: '+str(args))
    return result

def unpack(image, parts, root):
    run([sys.executable, ROM/'system/tools/mkbootimg/unpack_bootimg.py',
         '--boot_img', image, '--out', parts], stdout=subprocess.DEVNULL)
    root.mkdir()
    raw = run(['zstd', '-dc', parts/'ramdisk'], capture_output=True).stdout
    run(['cpio', '-idmu', '--no-absolute-filenames'], cwd=root, input=raw,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

def tree(root):
    result = {}
    for path in root.rglob('*'):
        relative = str(path.relative_to(root))
        mode = stat.S_IMODE(path.lstat().st_mode)
        if path.is_symlink():
            result[relative] = ['symlink', os.readlink(path), mode]
        elif path.is_file():
            result[relative] = ['file', sha(path), mode]
        elif path.is_dir():
            result[relative] = ['directory', mode]
        else:
            raise RuntimeError('Unexpected special file: '+relative)
    return result

assert base['sha256'] == '738556589abb2c35047879f14cfed63a05a6ed25c7c418a0209709622312376f'
image_input = BASE_DIR/base['image']
assert sha(image_input) == base['sha256']
assert compiled['baseline_policy_sha256'] == base['sepolicy_sha256']
assert compiled['neverallows_enforced'] and compiled['permissive_domains_unchanged']
assert sha(Path(compiled['policy'])) == compiled['candidate_policy_sha256']
assert sha(DEVICE/'rootdir/recovery/hardware.sh') == compiled['hardware_script_sha256']
for relative, expected in compiled['sources'].items():
    assert sha(DEVICE/relative) == expected

parts, root = WORK/'parts', WORK/'root'
unpack(image_input, parts, root)
before = tree(root)
assert sha(root/'sepolicy') == compiled['baseline_policy_sha256']
assert 'write /sys/module/firmware_class/parameters/path /firmware/image' in (root/'init.recovery.qcom.rc').read_text()
shutil.copyfile(compiled['policy'], root/'sepolicy')
shutil.copyfile(DEVICE/'rootdir/recovery/hardware.sh', root/'system/bin/sheng-recovery-hardware')
after = tree(root)
changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
assert changed == ['sepolicy', 'system/bin/sheng-recovery-hardware'], changed

cpio, ramdisk = WORK/'ramdisk.cpio', WORK/'ramdisk.zst'
with cpio.open('wb') as output:
    run([HOST/'mkbootfs', '-d', ROM/'out/target/product/sheng', root], stdout=output)
run(['zstd', '-q', '-19', '-T4', '-f', cpio, '-o', ramdisk])
config = base['boot_layout']
image = WORK/'recovery.img'
cmdline = base['cmdline'].replace('sheng_recovery_test=r13-native-source-fast-touch',
                                 'sheng_recovery_test=r54-firmware-path')
assert 'sheng_recovery_test=r54-firmware-path' in cmdline
args = [sys.executable, ROM/'system/tools/mkbootimg/mkbootimg.py']
for flag, value in {
    'header_version': 2, 'pagesize': config['page_size'], 'base': config['base'],
    'kernel_offset': config['kernel_offset'], 'ramdisk_offset': config['ramdisk_offset'],
    'tags_offset': config['tags_offset'], 'dtb_offset': config['dtb_offset'],
    'second_offset': 0, 'os_version': config['recovery_os_version'],
    'os_patch_level': config['recovery_os_patch_level'], 'kernel': parts/'kernel',
    'ramdisk': ramdisk, 'dtb': parts/'dtb', 'recovery_dtbo': parts/'recovery_dtbo',
    'cmdline': cmdline, 'output': image,
}.items():
    args.extend(['--'+flag, value])
run(args)
run([HOST/'avbtool', 'add_hash_footer', '--image', image, '--partition_name', 'recovery',
     '--partition_size', config['partition_size'], '--algorithm', 'SHA256_RSA4096',
     '--key', ROM/'external/avb/test/data/testkey_rsa4096.pem'])
run([HOST/'avbtool', 'verify_image', '--image', image])
verified, verified_root = WORK/'verified', WORK/'verified-root'
unpack(image, verified, verified_root)
assert tree(verified_root) == after, 'Embedded file contents or modes differ'
for part in ('kernel', 'dtb', 'recovery_dtbo'):
    assert sha(parts/part) == sha(verified/part), part
assert image.stat().st_size == 104857600
DEST.mkdir(exist_ok=False)
target = DEST/'lineage-24.0-sheng-recovery-r54-firmware-path.img'
shutil.copyfile(image, target)
assert sha(target) == sha(image)
receipt = {
    'revision': 54, 'scope': 'Recovery firmware search path and guarded ADSP startup',
    'image': str(target), 'sha256': sha(target), 'bytes': target.stat().st_size,
    'base_image_sha256': base['sha256'], 'changed_ramdisk_files': changed,
    'kernel_and_dtb_and_dtbo_unchanged': True, 'all_other_embedded_files_and_modes_unchanged': True,
    'policy_build': compiled, 'avb_verified': True, 'embedded_readback_verified': True,
    'full_product_build_passed': False, 'installed': False, 'hardware_boot_tested': False,
    'cmdline': cmdline, 'work': str(WORK),
}
(DEST/'build-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
(REVIEW/'recovery-package-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
(DEST/'SHA256SUMS').write_text(sha(target)+'  '+target.name+'\n')
print(json.dumps(receipt, indent=2))
