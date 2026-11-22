#!/usr/bin/env python3
"""Offline trial images from exact live parents; no public source edits or flash."""
from pathlib import Path
import importlib.util
import json
import lzma
import subprocess
import sys

HERE = Path(__file__).resolve().parent
W = HERE.parents[4]
sys.path.insert(0, str(W / 'scripts'))
sys.path.insert(0, str(HERE.parents[1] / 'tools'))
from build_sheng_fastbootd_cold_trace import parse_cpio, sha
from package_sheng_recovery_modules import replace_records

PARENTS = {
    'boot': ('/mnt/e/sheng-fastbootd-cold-trace-20261119-candidate02/images/boot.img', '8ddc10d21163972c7d416c6f3bb9685b907990bd0b773a30846c7b82698cb7be'),
    'vendor_boot': ('/mnt/e/sheng-usb-udc-bind-pair-20261120-candidate01/images/vendor_boot.img', '622649e30cb39dd43dd86e04ec193b6b085bbfa03a65f7cdb085622c5ccc58c7'),
    'init_boot': ('/mnt/e/sheng-ksu-fallback-rehearsal-20261120/init_boot_b.before.magisk.readback.img', 'efb0c7c3558bedf2974e4b7ec1bc4a896e84c0952c7e59a5dd7af83bc565a93e'),
}


def main():
    trial = Path(sys.argv[1]).resolve(strict=True)
    out = Path(sys.argv[2]).resolve()
    out.mkdir(exist_ok=False)
    (out / 'images').mkdir()
    (out / 'parents').mkdir()
    logs = out / 'logs'; logs.mkdir()
    a = Path('/root/sheng-pixelos/android')
    avbpath = a / 'external/avb/avbtool.py'
    spec = importlib.util.spec_from_file_location('avbtool', avbpath)
    avb = importlib.util.module_from_spec(spec); spec.loader.exec_module(avb)
    q = json.loads((trial / 'linked/qualification.json').read_text())
    assert q['passed'] and q['export_crcs_identical']
    modules = json.loads((trial / 'module-btf-crc-check.json').read_text())
    assert len(modules) == 343 and all(r['returncode'] == 0 for r in modules)

    def run(cmd, label, data=None):
        p = subprocess.run(list(map(str, cmd)), input=data, capture_output=True, timeout=120)
        (logs / (label + '.stdout')).write_bytes(p.stdout)
        (logs / (label + '.stderr')).write_bytes(p.stderr)
        assert p.returncode == 0, (label, p.stderr)
        return p.stdout

    def info(p):
        handler = avb.ImageHandler(str(p), read_only=True)
        try:
            return avb.Avb()._parse_image(handler)
        finally:
            handler._image.close()

    results = {}
    for name, (path, expected) in PARENTS.items():
        original = Path(path); assert sha(original) == expected
        parent = out / 'parents' / (name + '.img')
        parent.symlink_to(original)
        run(['python3', avbpath, 'verify_image', '--image', parent], name + '-parent-avb')
        parts = out / (name + '-before')
        raw = run(['python3', a / 'system/tools/mkbootimg/unpack_bootimg.py', '--boot_img', parent,
                   '--out', parts, '--format', 'mkbootimg', '-0'], name + '-unpack')
        args = [x.decode() for x in raw[:-1].split(b'\0')]
        before = args.copy(); changed = []
        if name == 'boot':
            assert sha(parts / 'kernel') == '79e82a8118e4edd571f6ce438104f5107b0de82180e68b44be4eb9b27372e745'
            args[args.index('--kernel') + 1] = str(trial / 'linked/kernel/Image')
            changed = ['kernel']
        else:
            flag = '--vendor_ramdisk_fragment' if name == 'vendor_boot' else '--ramdisk'
            idx = args.index(flag) + 1
            plain = run(['lz4', '-dc', args[idx]], name + '-decompress')
            entries, _ = parse_cpio(plain); inv = {e['name']: e for e in entries}
            if name == 'vendor_boot':
                fstab = inv['system/etc/fstab.qcom']['payload']
                assert fstab.count(b',overlay=off') == 2
                assert all(line.split()[:2] == [b'system', b'/system'] for line in fstab.splitlines() if b',overlay=off' in line)
                replacements = {'system/etc/fstab.qcom': fstab.replace(b',overlay=off', b'')}
                assert b'overlay=off' not in replacements['system/etc/fstab.qcom']
            else:
                # Preserve the qualified Magisk executable and its overlay payload.
                # Magisk decompresses this saved original Android first-stage init.
                # The retained XZ uses ARM64 BCJ, unsupported by host liblzma.
                # Decode with the installed app's MagiskBoot and compare exact base.
                decode_receipt = W / 'reports/sheng-magisk-rootfix-trial-20261120a'
                assert inv['.backup/init.xz']['payload'] == (decode_receipt / 'original-init.xz').read_bytes()
                old_init = (decode_receipt / 'original-init-from-magisk').read_bytes()
                baseline = a / 'out-clean-ota-20261116/target/product/sheng/ramdisk/init'
                assert old_init == baseline.read_bytes(), 'Magisk backup is not the known clean init'
                replacements = {'.backup/init.xz': lzma.compress((trial / 'linked/init').read_bytes(), preset=9, check=lzma.CHECK_CRC32)}
            changed = sorted(replacements)
            packed = replace_records(plain, replacements, parse_cpio)
            compressed = out / (name + '-candidate.lz4')
            compressed.write_bytes(run(['lz4', '-l', '-9', '-c'], name + '-compress', packed))
            args[idx] = str(compressed)
        image = out / 'images' / (name + '.img')
        run(['python3', a / 'system/tools/mkbootimg/mkbootimg.py', *args,
             '--vendor_boot' if name == 'vendor_boot' else '--output', image], name + '-pack')
        _, header, desc, _ = info(parent)
        assert header.algorithm_type == 0
        hashes = [d for d in desc if isinstance(d, avb.AvbHashDescriptor)]
        assert len(hashes) == 1 and hashes[0].partition_name == name
        h = hashes[0]
        cmd = ['python3', avbpath, 'add_hash_footer', '--image', image, '--partition_size', parent.stat().st_size,
               '--partition_name', name, '--algorithm', 'NONE', '--salt', h.salt.hex(), '--hash_algorithm', h.hash_algorithm,
               '--flags', header.flags, '--rollback_index', header.rollback_index, '--rollback_index_location', header.rollback_index_location]
        for d in desc:
            if isinstance(d, avb.AvbPropertyDescriptor):
                cmd += ['--prop', d.key + ':' + d.value.decode()]
            else:
                assert isinstance(d, avb.AvbHashDescriptor)
        run(cmd, name + '-footer')
        run(['python3', avbpath, 'verify_image', '--image', image], name + '-verify')
        _, after_header, after_desc, _ = info(image)
        assert vars(header) == vars(after_header)
        assert [d.encode() for d in desc if not isinstance(d, avb.AvbHashDescriptor)] == [d.encode() for d in after_desc if not isinstance(d, avb.AvbHashDescriptor)]
        finalparts = out / (name + '-after')
        finalraw = run(['python3', a / 'system/tools/mkbootimg/unpack_bootimg.py', '--boot_img', image,
                        '--out', finalparts, '--format', 'mkbootimg', '-0'], name + '-readback')
        finalargs = [x.decode() for x in finalraw[:-1].split(b'\0')]
        normalize = lambda argv, folder: ['PART/' + Path(x).name if x.startswith(str(folder) + '/') else x for x in argv]
        assert normalize(before, parts) == normalize(finalargs, finalparts)
        for p in parts.iterdir():
            if not p.is_file(): continue
            if name == 'boot' and p.name == 'kernel':
                assert (finalparts / p.name).read_bytes() == (trial / 'linked/kernel/Image').read_bytes()
            elif 'ramdisk' in p.name and name != 'boot':
                assert run(['lz4', '-dc', finalparts / p.name], name + '-verify-cpio') == packed
            else:
                assert p.read_bytes() == (finalparts / p.name).read_bytes(), p
        results[name] = dict(path=str(image), sha256=sha(image), bytes=image.stat().st_size, changed=changed,
                             parent_path=path, parent_sha256=expected)
    (out / 'qualification.json').write_text(json.dumps(dict(passed=True, images=results,
        changed_partitions=['boot_b', 'vendor_boot_b', 'init_boot_b'], module_crcs_and_btf_verified=343,
        modules_unchanged=True, overlay_off_removed=True, magisk_binary_unchanged=True,
        standalone_avb_verified=True, full_avb_chain_verified=False, recovery_unchanged=True,
        flashed=False, combined_runtime_verified=False), indent=2))
    print('Offline image qualification passed:', out)


if __name__ == '__main__':
    main()
