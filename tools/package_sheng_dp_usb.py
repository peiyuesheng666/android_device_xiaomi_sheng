#!/usr/bin/env python3
"""Repack the exact active vendor_boot baseline, changing only qualified signed modules or selected fstab flags."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--name', default='dp-usb-kernel-20261118')
parser.add_argument('--system-overlay-off', action='store_true',
                    help='diagnostic: opt only /system out of first-stage overlayfs')
parser.add_argument('--product-overlay-off', action='store_true',
                    help='diagnostic: opt only /product out of first-stage overlayfs')
args = parser.parse_args()
overlay_opt_out = tuple(part for part, enabled in ((b'system', args.system_overlay_off),
                                                   (b'product', args.product_overlay_off)) if enabled)
def report_path(kind):
    name = 'dp-usb-kernel-' + kind + '-20261118' if args.name == 'dp-usb-kernel-20261118' else args.name + '-' + kind
    return workspace / 'reports' / (name + '.json')
workspace = Path(__file__).resolve().parents[4]
artifact = workspace / 'artifacts' / args.name
baseline = json.loads(report_path('baseline').read_text())
qualification = json.loads(report_path('qualification').read_text())
assert qualification['passed']
source = artifact / ('vendor_boot' + baseline['slot'] + '.before.img')
sha = lambda data: hashlib.sha256(data).hexdigest()
assert sha(source.read_bytes()) == baseline['sha256']
android = Path('/root/sheng-pixelos/android')
build = Path('/root/sheng-pixelos/diagnostics/ksu-rawdump-20261117') / args.name / 'package'
build.mkdir(parents=True, exist_ok=True)
env = dict(os.environ, LANG='C.UTF-8', LC_ALL='C.UTF-8')
unpack = android / 'system/tools/mkbootimg/unpack_bootimg.py'
mkboot = android / 'system/tools/mkbootimg/mkbootimg.py'
avb = android / 'external/avb/avbtool.py'
info = subprocess.check_output([str(avb), 'info_image', '--image', str(source)], text=True, env=env)
(build / 'baseline-avb.txt').write_text(info)
assert re.search(r'Algorithm:\s+NONE\b', info), 'A signed baseline requires its matching image signing policy'
salt = re.search(r'Salt:\s+([0-9a-f]+)', info).group(1)
argv = subprocess.check_output(['python3', str(unpack), '--boot_img', str(source),
                               '--out', str(build / 'parts'), '--format', 'mkbootimg', '-0'], env=env)
argv = [part.decode() for part in argv.rstrip(b'\0').split(b'\0')]
ramdisks = [argv[i + 1] for i, value in enumerate(argv) if value == '--vendor_ramdisk_fragment']
assert len(ramdisks) == 1, ramdisks
ramdisk = Path(ramdisks[0])
plain = subprocess.check_output(['lz4', '-dc', str(ramdisk)])
names = [row['name'] for row in qualification['modules']]
assert (names or overlay_opt_out) and len(names) == len(set(names))
assert all(re.fullmatch(r'[a-zA-Z0-9_-]+', name) for name in names)
replacements = {name + '.ko': (artifact / (name + '.signed.ko')).read_bytes() for name in names}
for row in qualification['modules']:
    assert sha(replacements[row['name'] + '.ko']) == row['signed_sha256']


def fstab_overlay_off(payload, partition):
    lines = payload.splitlines(keepends=True)
    filesystems = []
    for index, line in enumerate(lines):
        if line.lstrip().startswith(b'#'):
            continue
        fields = list(re.finditer(rb'\S+', line))
        if len(fields) < 2 or fields[1].group() != b'/' + partition:
            continue
        assert len(fields) >= 5 and fields[0].group() == partition
        flags = fields[4].group().split(b',')
        assert b'first_stage_mount' in flags and b'logical' in flags
        assert not any(flag.startswith(b'overlay=') for flag in flags)
        filesystems.append(fields[2].group())
        end = fields[4].end()
        lines[index] = line[:end] + b',overlay=off' + line[end:]
    assert sorted(filesystems) == [b'erofs', b'ext4']
    return b''.join(lines)


def archive(data, replace=False):
    pos, result, inventory, changed = 0, bytearray(), [], []
    while pos + 110 <= len(data):
        magic = data[pos:pos + 6]
        if magic not in (b'070701', b'070702'):
            assert not data[pos:].strip(b'\0')
            break
        fields = [int(data[pos + 6 + i * 8:pos + 14 + i * 8], 16) for i in range(13)]
        name = data[pos + 110:pos + 110 + fields[11]]
        pos = (pos + 110 + fields[11] + 3) & ~3
        payload = data[pos:pos + fields[6]]
        assert len(payload) == fields[6]
        pos = (pos + fields[6] + 3) & ~3
        path = name[:-1].decode()
        if replace and Path(path).name in replacements:
            changed.append({'path': path, 'before': sha(payload), 'after': sha(replacements[Path(path).name])})
            payload = replacements[Path(path).name]
        if replace and overlay_opt_out and path == 'system/etc/fstab.qcom':
            fixed = payload
            for partition in overlay_opt_out:
                fixed = fstab_overlay_off(fixed, partition)
            changed.append({'path': path, 'before': sha(payload), 'after': sha(fixed)})
            payload = fixed
        inventory.append((path, fields[1], sha(payload)))
        fields[6] = len(payload)
        if magic == b'070702':
            fields[12] = sum(payload) & 0xffffffff
        result += magic + b''.join(f'{value:08x}'.encode() for value in fields) + name
        result += b'\0' * (-len(result) % 4)
        result += payload
        result += b'\0' * (-len(result) % 4)
    result += b'\0' * (-len(result) % 512)
    return bytes(result), inventory, changed


_, before, _ = archive(plain)
packed, expected, changed = archive(plain, replace=True)
expected_names = set(replacements) | ({'fstab.qcom'} if overlay_opt_out else set())
assert {Path(row['path']).name for row in changed} == expected_names and len(changed) == len(expected_names)
ramdisk_new = build / 'vendor_ramdisk-dp-usb.lz4'
ramdisk_new.write_bytes(subprocess.check_output(['lz4', '-l', '-9', '-c'], input=packed))
assert archive(subprocess.check_output(['lz4', '-dc', str(ramdisk_new)]))[1] == expected
assert len(before) == len(expected)
argv[argv.index(str(ramdisk))] = str(ramdisk_new)
image = artifact / 'candidate/vendor_boot.img'
image.parent.mkdir(exist_ok=True)
subprocess.run(['python3', str(mkboot), *argv, '--vendor_boot', str(image)], check=True, env=env)
subprocess.run([str(avb), 'add_hash_footer', '--image', str(image), '--partition_size', str(baseline['bytes']),
                '--partition_name', 'vendor_boot', '--salt', salt], check=True, env=env)
subprocess.run([str(avb), 'verify_image', '--image', str(image)], check=True, env=env)
after_parts = build / 'readback'
subprocess.run(['python3', str(unpack), '--boot_img', str(image), '--out', str(after_parts)],
               check=True, env=env, stdout=subprocess.DEVNULL)
for name in ('dtb', 'bootconfig'):
    assert (build / 'parts' / name).read_bytes() == (after_parts / name).read_bytes(), name
final_args = subprocess.check_output(['python3', str(unpack), '--boot_img', str(image),
                                      '--out', str(after_parts), '--format', 'mkbootimg', '-0'], env=env)
final_args = [part.decode() for part in final_args.rstrip(b'\0').split(b'\0')]
final_ramdisk = Path(final_args[final_args.index('--vendor_ramdisk_fragment') + 1])
assert archive(subprocess.check_output(['lz4', '-dc', str(final_ramdisk)]))[1] == expected
report = dict(passed=True, installed=False, baseline=baseline, changed=changed,
              candidate_path=str(image.relative_to(workspace)),
              candidate_sha256=sha(image.read_bytes()), candidate_bytes=image.stat().st_size,
              dtb_unchanged=True, bootconfig_unchanged=True,
              cpio_entry_count=len(expected), system_overlay_off=args.system_overlay_off,
              product_overlay_off=args.product_overlay_off,
              only_selected_module_payloads_changed=not overlay_opt_out,
              actual_module_payload_changes=sum(row['path'].endswith('.ko') and row['before'] != row['after']
                                                for row in changed))
report_path('package').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
