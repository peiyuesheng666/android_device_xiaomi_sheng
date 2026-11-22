#!/usr/bin/env python3
"""Read physical images to RAM, reconcile root AVB offline, and verify its chain.

Requires identified root Recovery b and an unchanged audited metadata capture.
No partition writes, mounts, mapping, reboots, slot changes or flashing. RAM
images exist for one WSL lifetime; only hashes, footer evidence and candidate
root vbmeta persist. This is NOT Android or hardware root-of-trust acceptance.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile

from read_physical_backing import SIZES, extents_for, read_command, digest
from storage_guard import require_build_space

SERIAL = 'ca10ede3'
DIRECT = {
    'boot': 201326592, 'dtbo': 25165824, 'init_boot': 8388608,
    'recovery': 104857600, 'vendor_boot': 100663296,
}
LOGICAL = ('product', 'odm', 'vendor', 'vendor_dlkm', 'system_dlkm')

WARNING = ('OFFLINE CAPTURED-CHAIN CANDIDATE ONLY. Do not flash root vbmeta alone. '
           'It requires the exact trial system/system_ext/vbmeta_system set and all '
           'captured companion hashes. No Android, hardware trust, boot, Recovery or '
           'KSU acceptance is claimed. Never relock the bootloader based on this test.\n')


def mark_unqualified(out):
    # Leave the warning even when capture/signing/verification raises an error.
    (out / 'DO_NOT_FLASH.txt').write_text(WARNING)


def verification_commands(avbpath, scratch, root_key, child_key, chain_key, rollback):
    # This retained avbtool propagates --key to recursive children. These use
    # different keys, so verify each level with its own pinned key. The caller
    # must also prove child_key encodes the exact signed chain descriptor key.
    return [
        ['python3', str(avbpath), 'verify_image', '--image', str(scratch / 'vbmeta.img'),
         '--key', str(root_key), '--expected_chain_partition',
         f'vbmeta_system:{rollback}:{chain_key}'],
        ['python3', str(avbpath), 'verify_image', '--image', str(scratch / 'vbmeta_system.img'),
         '--key', str(child_key)],
    ]


def footer_positions(tail, image_bytes, footer_bytes=64):
    """Find footer-sized aligned candidates; callers must fully validate them."""
    if image_bytes < len(tail) or footer_bytes <= 0:
        raise ValueError('Invalid tail bounds')
    result, start = [], 0
    while True:
        offset = tail.find(b'AVBf', start)
        if offset < 0:
            return result
        absolute = image_bytes - len(tail) + offset
        if absolute % 64 == 0 and offset + footer_bytes <= len(tail):
            result.append((absolute, offset))
        start = offset + 1


def replace_descriptors(descriptors, replacements, classes):
    result, seen = [], set()
    for d in descriptors:
        if isinstance(d, classes) and d.partition_name in replacements:
            name = d.partition_name
            if name in seen:
                raise ValueError('Duplicate protected partition in parent')
            result.append(replacements[name])
            seen.add(name)
        else:
            result.append(d)
    if seen != set(replacements):
        raise ValueError('Replacement partition absent from signed parent')
    return result


def public_key(path, header):
    start = header.SIZE + header.authentication_data_block_size + header.public_key_offset
    with path.open('rb') as stream:
        stream.seek(start)
        value = stream.read(header.public_key_size)
    if len(value) != header.public_key_size:
        raise ValueError('Short embedded public key')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--adb', type=Path, required=True)
    parser.add_argument('--trial', type=Path, required=True)
    parser.add_argument('--parents', type=Path, required=True)
    parser.add_argument('--snapshot-audit', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    rom, adb, trial, parents, snapshot = (p.resolve(strict=True) for p in
        (args.rom, args.adb, args.trial, args.parents, args.snapshot_audit))
    out = args.out.resolve()
    if out.exists():
        parser.error('Output must be new; preserve earlier evidence')
    storage = require_build_space(out, minimum_output=512 * 1024**2)
    q = json.loads((trial / 'qualification.json').read_text())
    assert q['passed'] and q['original_parents_unchanged']
    assert not q['full_avb_chain_verified'] and not q['flashed']
    for name in ('system', 'system_ext'):
        assert digest(trial / 'images' / (name + '.img')) == q['images'][name]['sha256']
    assert digest(trial / 'images/vbmeta_system.img') == q['vbmeta_system']['sha256']
    snapshot_q = json.loads((snapshot / 'result.json').read_text())
    assert not snapshot_q['snapshot_metadata_indicates_active_update']
    assert (snapshot / 'snapshot-files02/ota/state').read_bytes() == b''
    assert not list((snapshot / 'snapshot-files02/ota/snapshots').iterdir())
    assert digest(snapshot / 'metadata.pristine.img') == snapshot_q['metadata_pristine_sha256']
    avbpath = rom / 'external/avb/avbtool.py'
    spec = importlib.util.spec_from_file_location('avb', avbpath)
    avb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(avb)
    host = rom / 'out-clean-ota-20261116/host/linux-x86/bin'
    env = dict(os.environ, PATH=str(host) + ':' + os.environ['PATH'])
    prefix = [str(adb), '-s', SERIAL]
    out.mkdir(parents=True)
    mark_unqualified(out)
    commands = []

    def shell(command, timeout=120):
        p = subprocess.run(prefix + ['shell', 'sh -s'], input=('set -eu\n' + command + '\n').encode(),
                           capture_output=True, timeout=timeout)
        p.check_returncode()
        return p.stdout.decode().replace('\r', '').strip()

    def identity():
        return shell('getprop ro.serialno; getprop ro.product.device; '
                     'getprop ro.boot.slot_suffix; getprop init.svc.recovery; '
                     'id -u; cat /proc/sys/kernel/random/boot_id').splitlines()

    before = identity()
    assert len(before) == 6 and before[:5] == [SERIAL, 'sheng', '_b', 'running', '0']
    assert shell('sha256sum /dev/block/by-name/metadata').split()[0] == snapshot_q['metadata_pristine_sha256']
    original_hashes = {}
    for name in ('vbmeta', 'vbmeta_system'):
        original_hashes[name] = digest(parents / (name + '.img'))
        assert shell('sha256sum /dev/block/by-name/' + name + '_b').split()[0] == original_hashes[name]

    def metadata():
        data = subprocess.check_output(prefix + ['exec-out',
            'dd if=/dev/block/by-name/super bs=1048576 count=1 2>/dev/null'], timeout=30)
        assert len(data) == 1024**2
        return data

    super_metadata = metadata()
    meta = out / 'super-metadata.bin'
    meta.write_bytes(super_metadata)
    p = subprocess.run([host / 'lpdump', '--slot=1', meta], capture_output=True, timeout=30)
    (out / 'lpdump.stdout').write_bytes(p.stdout)
    (out / 'lpdump.stderr').write_bytes(p.stderr)
    p.check_returncode()
    layout = p.stdout.decode().replace('\r\n', '\n')
    super_bytes = int(shell('blockdev --getsize64 /dev/block/by-name/super'))
    plans = {name: extents_for(layout, name + '_b', super_bytes, SIZES[name + '_b'])
             for name in LOGICAL}
    for name, size in DIRECT.items():
        assert int(shell('blockdev --getsize64 /dev/block/by-name/' + name + '_b')) == size
    required_ram = sum(DIRECT.values()) + sum(SIZES[name + '_b'] for name in LOGICAL)
    ram_free = shutil.disk_usage('/dev/shm').free
    assert ram_free >= required_ram + 256 * 1024**2, 'Insufficient RAM filesystem; no disk fallback'

    def info(path):
        handler = avb.ImageHandler(str(path), read_only=True)
        try:
            return avb.Avb()._parse_image(handler)
        finally:
            handler._image.close()

    root = parents / 'vbmeta.img'
    _, root_header, root_descriptors, _ = info(root)
    assert root_header.algorithm_type == 2 and root_header.flags == 3
    assert root_header.public_key_metadata_size == 0
    assert avb.verify_vbmeta_signature(root_header, root.read_bytes())
    protected_types = (avb.AvbHashDescriptor, avb.AvbHashtreeDescriptor)
    old_descriptors = {d.partition_name: d for d in root_descriptors if isinstance(d, protected_types)}
    assert set(old_descriptors) == set(DIRECT) | (set(LOGICAL) - {'product'})
    records, replacements = {}, {}
    with tempfile.TemporaryDirectory(prefix='sheng-avb-chain-', dir='/dev/shm') as temp:
        scratch = Path(temp)
        for name in (*DIRECT, *LOGICAL):
            if name in DIRECT:
                size = DIRECT[name]
                reads = ['dd if=/dev/block/by-name/' + name + '_b bs=1048576 2>/dev/null']
                attributes = None
            else:
                extents, attributes = plans[name]
                size = SIZES[name + '_b']
                reads = [read_command(e) for e in extents]
            image = scratch / (name + '.img')
            with image.open('xb') as stream:
                for index, read in enumerate(reads):
                    start = stream.tell()
                    p = subprocess.run(prefix + ['exec-out', read], stdout=stream,
                                       stderr=subprocess.PIPE, timeout=300)
                    (out / f'{name}-read-{index}.stderr').write_bytes(p.stderr)
                    p.check_returncode()
                    expected = size if name in DIRECT else plans[name][0][index]['bytes']
                    assert stream.tell() - start == expected, 'Truncated or contaminated binary capture'
            assert image.stat().st_size == size
            checksum = digest(image)
            if name in DIRECT:
                device_checksum = shell('sha256sum /dev/block/by-name/' + name + '_b').split()[0]
            else:
                device_checksum = shell('{ ' + '; '.join(read + ' || exit 1' for read in reads) +
                                        '; } | sha256sum', timeout=300).split()[0]
            assert checksum == device_checksum, 'RAM/device physical readback mismatch'
            assert identity() == before and metadata() == super_metadata
            with image.open('rb') as stream:
                stream.seek(max(0, size - 8 * 1024**2))
                tail = stream.read()
            (out / (name + '-tail.bin')).write_bytes(tail)
            valid = []
            for absolute, relative in footer_positions(tail, size):
                try:
                    footer = avb.AvbFooter(tail[relative:relative + avb.AvbFooter.SIZE])
                except (LookupError, ValueError, AssertionError):
                    continue
                if not (0 < footer.original_image_size <= footer.vbmeta_offset and
                        256 <= footer.vbmeta_size <= 1024**2 and
                        footer.vbmeta_offset + footer.vbmeta_size <= absolute):
                    continue
                with image.open('rb') as stream:
                    stream.seek(footer.vbmeta_offset)
                    blob = stream.read(footer.vbmeta_size)
                if blob[:4] != b'AVB0':
                    continue
                embedded = out / f'{name}-embedded-{absolute}.img'
                embedded.write_bytes(blob)
                _, hdr, descriptors, _ = info(embedded)
                matches = [d for d in descriptors if isinstance(d, protected_types) and d.partition_name == name]
                if len(matches) != 1 or hdr.flags != 0 or not avb.verify_vbmeta_signature(hdr, blob):
                    continue
                if matches[0].image_size > footer.original_image_size:
                    continue
                if name in old_descriptors:
                    assert type(matches[0]) is type(old_descriptors[name]), 'Live descriptor type changed'
                elif name == 'product':
                    assert isinstance(matches[0], avb.AvbHashtreeDescriptor)
                valid.append((absolute, hdr, matches[0]))
            if valid:
                assert len({item[2].encode() for item in valid}) == 1, 'Ambiguous footer descriptors'
                absolute, hdr, descriptor = valid[-1]
                assert descriptor.flags == 0 and descriptor.hash_algorithm == 'sha256'
                origin = 'validated embedded live vbmeta'
                trailing = size - absolute - avb.AvbFooter.SIZE
            else:
                assert name in old_descriptors or name == 'product', 'No live descriptor or signed-parent descriptor'
                descriptor = old_descriptors.get(name)
                origin = 'signed parent; full data/tree verification still required below'
                trailing = None
            if name in old_descriptors:
                replacements[name] = descriptor
            records[name] = dict(bytes=size, sha256=checksum, device_sha256=device_checksum,
                                 attributes=attributes, descriptor_origin=origin,
                                 footer_candidates=len(valid), trailing_bytes_after_footer=trailing,
                                 raw_super_write_authorized=False)
            (out / 'captured-physical-images.json').write_text(json.dumps(records, indent=2))
            print(json.dumps(dict(captured=name, bytes=size, hash_matched=True,
                                  footer_candidates=len(valid))), flush=True)

        new_descriptors = replace_descriptors(root_descriptors, replacements, protected_types)
        blob = avb.Avb()._generate_vbmeta_blob(
            algorithm_name='SHA256_RSA4096', key_path=str(rom / 'external/avb/test/data/testkey_rsa4096.pem'),
            public_key_metadata_path=None, descriptors=new_descriptors,
            chain_partitions_use_ab=None, chain_partitions_do_not_use_ab=None,
            rollback_index=root_header.rollback_index, flags=0,
            rollback_index_location=root_header.rollback_index_location,
            props=None, props_from_file=None, kernel_cmdlines=None,
            setup_rootfs_from_kernel=None, ht_desc_to_setup=None,
            include_descriptors_from_image=None, signing_helper=None,
            signing_helper_with_files=None, release_string=root_header.release_string,
            append_to_release_string=None,
            required_libavb_version_minor=root_header.required_libavb_version_minor)
        assert len(blob) <= root.stat().st_size
        candidate = out / 'vbmeta-flags0-candidate.img'
        candidate.write_bytes(blob + b'\0' * (root.stat().st_size - len(blob)))
        _, new_header, parsed_descriptors, _ = info(candidate)
        old_fields, new_fields = vars(root_header).copy(), vars(new_header).copy()
        assert old_fields.pop('flags') == 3 and new_fields.pop('flags') == 0
        assert old_fields == new_fields
        assert public_key(root, root_header) == public_key(candidate, new_header)
        assert avb.verify_vbmeta_signature(new_header, candidate.read_bytes())
        assert [d.encode() for d in root_descriptors if not isinstance(d, protected_types)] == [
            d.encode() for d in parsed_descriptors if not isinstance(d, protected_types)]
        changed = [name for name in old_descriptors if old_descriptors[name].encode() != replacements[name].encode()]
        chains = [d for d in parsed_descriptors if isinstance(d, avb.AvbChainPartitionDescriptor)]
        assert len(chains) == 1 and chains[0].partition_name == 'vbmeta_system'
        chain = chains[0]
        child = trial / 'images/vbmeta_system.img'
        _, child_header, child_descriptors, _ = info(child)
        assert child_header.flags == 0 and public_key(child, child_header) == chain.public_key
        assert not any(isinstance(d, avb.AvbChainPartitionDescriptor) for d in child_descriptors), 'Unverified deeper chain'
        child_key = rom / 'external/avb/test/data/testkey_rsa2048.pem'
        with avb.load_public_key(str(child_key)) as loaded_key:
            assert loaded_key.encode() == chain.public_key, 'Child PEM does not match signed parent chain key'
        key = out / 'expected-vbmeta_system.avbpubkey'
        key.write_bytes(chain.public_key)
        for name in ('system', 'system_ext', 'vbmeta_system'):
            (scratch / (name + '.img')).symlink_to(trial / 'images' / (name + '.img'))
        (scratch / 'vbmeta.img').symlink_to(candidate)
        commands = verification_commands(avbpath, scratch,
            rom / 'external/avb/test/data/testkey_rsa4096.pem', child_key,
            key, chain.rollback_index_location)
        (out / 'full-chain-command.json').write_text(json.dumps(commands, indent=2))
        for index, command in enumerate(commands):
            p = subprocess.run(command, capture_output=True, env=env, cwd=rom, timeout=600)
            (out / f'full-chain-{index}.stdout').write_bytes(p.stdout)
            (out / f'full-chain-{index}.stderr').write_bytes(p.stderr)
            p.check_returncode()
        assert identity() == before and metadata() == super_metadata
        assert shell('sha256sum /dev/block/by-name/metadata').split()[0] == snapshot_q['metadata_pristine_sha256']
        for name, checksum in original_hashes.items():
            assert shell('sha256sum /dev/block/by-name/' + name + '_b').split()[0] == checksum
        final_hashes = {}
        for name, record in records.items():
            if name in DIRECT:
                actual = shell('sha256sum /dev/block/by-name/' + name + '_b').split()[0]
            else:
                reads = [read_command(e) for e in plans[name][0]]
                actual = shell('{ ' + '; '.join(read + ' || exit 1' for read in reads) +
                               '; } | sha256sum', timeout=300).split()[0]
            assert actual == record['sha256'], 'Captured companion changed before final qualification'
            final_hashes[name] = actual
        assert identity() == before and metadata() == super_metadata
        for name in ('system', 'system_ext'):
            assert digest(trial / 'images' / (name + '.img')) == q['images'][name]['sha256']
        assert digest(child) == q['vbmeta_system']['sha256']
        receipt = dict(passed=True, serial=SERIAL, slot='_b', boot_id=before[-1],
                       storage_preflight=storage, ram_images_bytes=required_ram, ram_free_before=ram_free,
                       captures=records, candidate_root_vbmeta_sha256=digest(candidate),
                       final_device_companion_hashes=final_hashes,
                       candidate_root_flags=0, installed_root_flags_unchanged=3,
                       root_key_unchanged=True, chain_key_unchanged=True,
                       child_verification_key_matches_signed_chain=True,
                       verification_levels=2, deeper_child_chains_present=False,
                       changed_root_descriptors=changed, non_hash_root_descriptors_unchanged=True,
                       offline_captured_chain_verified=True, full_live_avb_chain_verified=False,
                       oem_hardware_root_of_trust_verified=False, android_runtime_verified=False,
                       actual_product_soong_build_verified=False,
                       metadata_unchanged=True, device_partition_writes=False,
                       device_read_access=True,
                       device_mount_changes=False, device_mapper_changes=False,
                       slot_switched=False, userdata_wiped=False, flashed=False)
        (out / 'qualification.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps({k: v for k, v in receipt.items() if k != 'captures'}, indent=2), flush=True)


if __name__ == '__main__':
    main()
