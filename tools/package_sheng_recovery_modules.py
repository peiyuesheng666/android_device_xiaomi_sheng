#!/usr/bin/env python3
"""Synchronize the six stale modules in the exact live sheng Recovery backup.

Offline image packaging only. Preserve every non-module CPIO record, Recovery
kernel/header, load/dependency metadata and AVB policy. Never flash or reboot.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

RECOVERY_SHA = '6435de948968ef2aeafb623f08d1579df35f26ab7100c80c77f8b45a7828748b'
VENDOR_SHA = 'b8ecb5c605631bdc14167e93801dc8b7f029a08bc2b0acaf866e007f8cd7f689'
CHANGED = {'dwc3-msm', 'qti_battery_charger', 'phy-msm-ssusb-qmp',
           'msm_drm', 'nanosic_driver', 'panel_event_notifier'}


def replace_records(plain, replacements, parse_cpio):
    entries, trailer = parse_cpio(plain)
    assert set(replacements) <= {e['name'] for e in entries}
    out = bytearray()
    for e in entries:
        if e['name'] not in replacements:
            out += e['raw']
            continue
        payload = replacements[e['name']]
        fields = e['fields'].copy()
        fields[6] = len(payload)
        magic = e['raw'][:6]
        if magic == b'070702':
            fields[12] = sum(payload) & 0xffffffff
        name = e['name'].encode() + b'\0'
        out += magic + b''.join(('%08x' % f).encode() for f in fields) + name
        out += b'\0' * (-len(out) % 4)
        out += payload
        out += b'\0' * (-len(out) % 4)
    out += trailer['raw']
    out += b'\0' * (-len(out) % 512)
    final, _ = parse_cpio(out)
    after = {e['name']: e for e in final}
    assert len(final) == len(entries)
    for e in entries:
        result = after[e['name']]
        if e['name'] not in replacements:
            assert e['raw'] == result['raw'], e['name']
        else:
            assert result['payload'] == replacements[e['name']]
            assert all(e['fields'][i] == result['fields'][i] for i in range(13) if i not in (6, 12))
    return bytes(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--android-root', type=Path, default=Path('/root/sheng-pixelos/android'))
    parser.add_argument('--recovery', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    w, a, out = args.workspace.resolve(), args.android_root.resolve(), args.out.resolve()
    sys.path.insert(0, str(w / 'scripts'))
    from build_sheng_fastbootd_cold_trace import sha, digest, parse_cpio
    from audit_kernel618_modules import ElfModule
    parent = args.recovery.resolve()
    vendor = w / 'artifacts/keyboard-panel-usb3-20261119/candidate/vendor_boot.img'
    assert sha(parent) == RECOVERY_SHA and sha(vendor) == VENDOR_SHA
    assert not out.exists(), 'Never overwrite a previous candidate'
    out.mkdir(parents=True)
    work = Path(tempfile.mkdtemp(prefix='sheng-recovery-sync-'))
    logs = out / 'logs'
    logs.mkdir()

    def run(command, label, data=None):
        p = subprocess.run(list(map(str, command)), input=data, capture_output=True, timeout=120)
        (logs / (label + '.stdout')).write_bytes(p.stdout)
        (logs / (label + '.stderr')).write_bytes(p.stderr)
        assert p.returncode == 0, label + ': ' + p.stderr.decode(errors='replace')
        return p.stdout

    unpack = a / 'system/tools/mkbootimg/unpack_bootimg.py'
    avbpath = a / 'external/avb/avbtool.py'
    spec = importlib.util.spec_from_file_location('avbtool', avbpath)
    avbtool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(avbtool)

    def avb_info(image):
        handler = avbtool.ImageHandler(str(image), read_only=True)
        try:
            return avbtool.Avb()._parse_image(handler)
        finally:
            handler._image.close()

    def unpack_args(image, label):
        folder = work / label
        raw = run(['python3', unpack, '--boot_img', image, '--out', folder,
                   '--format', 'mkbootimg', '-0'], label)
        assert raw.endswith(b'\0')
        return [f.decode() for f in raw[:-1].split(b'\0')], folder

    # Verify canonical recovery.img path without modifying the actual backup.
    (work / 'recovery.img').symlink_to(parent)
    run(['python3', avbpath, 'verify_image', '--image', work / 'recovery.img'], 'parent-footer')
    rargs, rparts = unpack_args(parent, 'recovery-before')
    vargs, _ = unpack_args(vendor, 'vendor-before')
    assert len([v for v in vargs if v == '--vendor_ramdisk_fragment']) == 1
    plain = run(['lz4', '-dc', rargs[rargs.index('--ramdisk') + 1]], 'recovery-cpio')
    vplain = run(['lz4', '-dc', vargs[vargs.index('--vendor_ramdisk_fragment') + 1]], 'vendor-cpio')
    re, _ = parse_cpio(plain)
    ve, _ = parse_cpio(vplain)
    ri, vi = {e['name']: e for e in re}, {e['name']: e for e in ve}
    rmods = {p for p in ri if p.endswith('.ko')}
    vmods = {p for p in vi if p.endswith('.ko')}
    assert rmods == vmods and len(rmods) == 343
    changed = {p for p in rmods if ri[p]['payload'] != vi[p]['payload']}
    assert changed == {'lib/modules/' + n + '.ko' for n in CHANGED}
    metadata = ['modules.alias', 'modules.dep', 'modules.softdep', 'modules.load']
    for name in metadata:
        path = 'lib/modules/' + name
        assert ri[path]['payload'] == vi[path]['payload'], 'Dependency/load metadata needs separate review: ' + name
    replacements = {p: vi[p]['payload'] for p in changed}
    records = []
    for p in sorted(changed):
        dest = work / Path(p).name
        dest.write_bytes(replacements[p])
        new = ElfModule(dest)
        oldfile = work / ('old-' + Path(p).name)
        oldfile.write_bytes(ri[p]['payload'])
        old = ElfModule(oldfile)
        assert new.info['vermagic'] == old.info['vermagic']
        records.append(dict(path=p, before_sha256=digest(ri[p]['payload']),
                            after_sha256=digest(replacements[p]),
                            loaded_note_sha256_expected=digest(new.get('.note.gnu.build-id')),
                            source_vermagic=new.info['vermagic']))
    packed = replace_records(plain, replacements, parse_cpio)
    compressed = work / 'recovery-module-sync.lz4'
    compressed.write_bytes(run(['lz4', '-l', '-9', '-c'], 'compress', packed))
    updated = rargs.copy()
    updated[updated.index('--ramdisk') + 1] = str(compressed)
    images = out / 'images'
    images.mkdir()
    image = images / 'recovery.img'
    run(['python3', a / 'system/tools/mkbootimg/mkbootimg.py', *updated, '--output', image], 'pack')
    _, header, desc, _ = avb_info(parent)
    assert header.algorithm_type == 0 and header.flags == 0
    assert len(desc) == 1 and isinstance(desc[0], avbtool.AvbHashDescriptor)
    hd = desc[0]
    assert hd.partition_name == 'recovery' and hd.flags == 0
    run(['python3', avbpath, 'add_hash_footer', '--image', image,
         '--partition_size', parent.stat().st_size, '--partition_name', 'recovery',
         '--algorithm', 'NONE', '--salt', hd.salt.hex(), '--hash_algorithm', hd.hash_algorithm,
         '--rollback_index', header.rollback_index,
         '--rollback_index_location', header.rollback_index_location], 'seal')
    run(['python3', avbpath, 'verify_image', '--image', image], 'candidate-footer')
    finalargs, finalparts = unpack_args(image, 'recovery-after')

    def normalized(argv, folder):
        return ['PART/' + Path(x).name if x.startswith(str(folder) + '/') else x for x in argv]

    assert normalized(rargs, rparts) == normalized(finalargs, finalparts)
    assert (rparts / 'kernel').read_bytes() == (finalparts / 'kernel').read_bytes()
    readback = run(['lz4', '-dc', finalargs[finalargs.index('--ramdisk') + 1]], 'cpio-readback')
    assert readback == packed
    finalentries, _ = parse_cpio(readback)
    finalmodules = {e['name']: digest(e['payload']) for e in finalentries if e['name'].endswith('.ko')}
    assert finalmodules == {p: digest(vi[p]['payload']) for p in vmods}
    _, afterheader, afterdesc, _ = avb_info(image)
    assert (header.algorithm_type, header.flags, header.rollback_index, header.rollback_index_location) == (
        afterheader.algorithm_type, afterheader.flags, afterheader.rollback_index, afterheader.rollback_index_location)
    assert len(afterdesc) == 1 and afterdesc[0].salt == hd.salt
    receipt = dict(passed=True, offline_only=True, flashed=False, live_loaded_module_parity=False,
                   parent=dict(path=str(parent), sha256=RECOVERY_SHA), vendor_source_sha256=VENDOR_SHA,
                   image=dict(path=str(image), bytes=image.stat().st_size, sha256=sha(image)),
                   changed=records, total_module_count=343, identical_to_accepted_vendor_modules=True,
                   cpio_entries_excluding_trailer=len(re), unchanged_existing_entries=len(re) - len(changed),
                   non_module_cpio_records_byte_identical=True, dependency_and_load_metadata_identical=True,
                   header_args_unchanged=True, kernel_payload_bytes=(rparts / 'kernel').stat().st_size,
                   kernel_payload_unchanged=True, avb_policy_unchanged=True, standalone_footer_verified=True,
                   full_live_avb_chain_verified=False, retained_linux_scratch=str(work),
                   requires_existing_diagnostic_boot_and_vendor_for_cold_trace=True,
                   scope='Repack actual Recovery backup with six already-qualified module payloads; not a full ROM build')
    (out / 'qualification.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
