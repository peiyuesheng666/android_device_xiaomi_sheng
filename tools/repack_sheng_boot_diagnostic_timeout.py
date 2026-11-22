#!/usr/bin/env python3
"""Set a diagnostic deadline or preserve existing rawdump logs in a matched boot set."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def preserve_cmdline(cmdline):
    """Disable both writes and diagnostic return; reject ambiguous parameters."""
    words = cmdline.split()
    keys = ('sheng_bootlog.enable', 'sheng_bootlog.test_timeout')
    for key in keys:
        matches = [word for word in words if word.split('=', 1)[0] == key]
        if len(matches) != 1 or '=' not in matches[0]:
            raise ValueError('Missing or ambiguous parameter: ' + key)
        value = matches[0].split('=', 1)[1]
        if (key == keys[0] and value not in ('0', '1')) or (
                key == keys[1] and not re.fullmatch(r'[0-9]+', value)):
            raise ValueError('Invalid parameter: ' + key)
    return ' '.join(word.split('=', 1)[0] + '=0'
                    if word.split('=', 1)[0] in keys else word for word in words)


def capture_cmdline(cmdline, *, timeout, revision):
    """Explicit opt-in from a preserve-rawdump parent; never infer test mode.

    This only requests kernel parameters. It does not prove the logger starts,
    the firmware returns to bootloader, or any failure evidence is retained.
    """
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 10 <= timeout <= 600:
        raise ValueError('Capture timeout must be an integer in 10..600')
    if not isinstance(revision, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', revision):
        raise ValueError('Capture revision must fit the 64-byte kernel parameter')
    words = cmdline.split()
    keys = ('sheng_bootlog.enable', 'sheng_bootlog.test_timeout', 'sheng_bootlog.revision')
    values = {}
    for key in keys:
        if key in words:
            raise ValueError('Bare diagnostic parameter is ambiguous: ' + key)
        matches = [word for word in words if word.startswith(key + '=')]
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous parameter: ' + key)
        values[key] = matches[0].split('=', 1)[1]
    if values['sheng_bootlog.enable'] != '0' or values['sheng_bootlog.test_timeout'] != '0':
        raise ValueError('Capture must derive from an explicitly disabled parent')
    if revision == values['sheng_bootlog.revision']:
        raise ValueError('Capture needs a fresh evidence revision')
    holds = [word for word in words if word.split('=', 1)[0] == 'sheng_bootlog.pre_driver_hold_ms']
    if len(holds) > 1 or any(word != 'sheng_bootlog.pre_driver_hold_ms=0' for word in holds):
        raise ValueError('Do not silently inherit driver isolation')
    replacements = dict(zip(keys, ('1', str(timeout), revision)))
    return ' '.join(word.split('=', 1)[0]+'='+replacements[word.split('=', 1)[0]]
                    if word.split('=', 1)[0] in replacements else word for word in words)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--android-root', type=Path, required=True)
    parser.add_argument('--host-bin', type=Path, help='directory containing built Android image tools')
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--preserve-rawdump', action='store_true',
                      help='disable the rawdump writer for evidence collection')
    mode.add_argument('--timeout', type=int,
                        help='0 disables automatic return; diagnostic range is 10..600 seconds')
    args = parser.parse_args()
    if args.timeout not in (None, 0) and not 10 <= args.timeout <= 600:
        parser.error('--timeout must be 0 or between 10 and 600')
    rom, out = args.android_root.resolve(), args.out.resolve()
    package = json.loads(args.package.read_text())
    assert package['passed'] and package['avb_chain_verified']
    source = Path(package['images'])
    for name, row in package['new_images'].items():
        path = source/(name+'.img')
        assert path.stat().st_size == row['size'] and sha(path) == row['sha256'], name
    assert not out.exists(), 'Output must be a new directory'
    out.mkdir(parents=True)
    images = out/'images'
    images.mkdir()
    host = args.host_bin.resolve() if args.host_bin else rom/'out/host/linux-x86/bin'
    spec = importlib.util.spec_from_file_location('avbtool', rom/'external/avb/avbtool.py')
    avbtool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(avbtool)
    avb = avbtool.Avb()

    def run(argv, label, *, timeout=60):
        result = subprocess.run(list(map(str, argv)), capture_output=True, timeout=timeout)
        (out/(label+'.log')).write_bytes(result.stdout+result.stderr)
        if result.returncode:
            raise RuntimeError(label+': '+result.stderr.decode(errors='replace'))
        return result.stdout

    def parse(path):
        image = avbtool.ImageHandler(str(path), read_only=True)
        try:
            return avb._parse_image(image)
        finally:
            image._image.close()

    raw = run([host/'unpack_bootimg', '--boot_img', source/'boot.img', '--out', out/'original',
               '--format', 'mkbootimg', '-0'], 'unpack-original')
    fields = raw.split(b'\0')
    assert fields[-1] == b''
    argv = [field.decode() for field in fields[:-1]]
    index = argv.index('--cmdline')+1
    before = argv[index]
    if args.preserve_rawdump:
        after = preserve_cmdline(before)
        count = 1
    else:
        after, count = re.subn(r'(?<!\S)sheng_bootlog\.test_timeout=\d+(?=\s|$)',
                               'sheng_bootlog.test_timeout='+str(args.timeout), before)
    assert count == 1 and after != before
    assert 'sheng_bootlog.enable=1' in before
    argv[index] = after
    boot = images/'boot.img'
    run([host/'mkbootimg', *argv, '--output', boot], 'pack-boot')
    _, header, descriptors, _ = parse(source/'boot.img')
    descriptor = next(d for d in descriptors if isinstance(d, avbtool.AvbHashDescriptor))
    assert descriptor.partition_name == 'boot' and header.algorithm_type == 0
    command = [host/'avbtool', 'add_hash_footer', '--image', boot, '--partition_name', 'boot',
               '--partition_size', (source/'boot.img').stat().st_size, '--salt', descriptor.salt.hex(),
               '--hash_algorithm', descriptor.hash_algorithm, '--algorithm', 'NONE',
               '--rollback_index', header.rollback_index,
               '--rollback_index_location', header.rollback_index_location]
    for d in descriptors:
        if isinstance(d, avbtool.AvbPropertyDescriptor):
            command += ['--prop', d.key+':'+d.value.decode()]
        else:
            assert isinstance(d, avbtool.AvbHashDescriptor), 'Unexpected boot descriptor'
    run(command, 'seal-boot')
    run([host/'unpack_bootimg', '--boot_img', boot, '--out', out/'verified'], 'unpack-verify')
    for name in ('kernel', 'ramdisk'):
        if (out/'original'/name).exists():
            assert (out/'original'/name).read_bytes() == (out/'verified'/name).read_bytes(), name
    assert after.encode() in boot.read_bytes()[:4096]

    _, parent, old, _ = parse(source/'vbmeta.img')
    _, _, new_boot, _ = parse(boot)
    replacement = next(d for d in new_boot if isinstance(d, avbtool.AvbHashDescriptor))
    changed = [d for d in old if isinstance(d, avbtool.AvbHashDescriptor) and d.partition_name == 'boot']
    assert len(changed) == 1
    new = [replacement if d is changed[0] else d for d in old]
    algorithm = 'SHA256_RSA4096'
    assert parent.algorithm_type == avbtool.ALGORITHMS[algorithm].algorithm_type
    blob = avb._generate_vbmeta_blob(
        algorithm_name=algorithm, key_path=str(rom/'external/avb/test/data/testkey_rsa4096.pem'),
        public_key_metadata_path=None, descriptors=new, chain_partitions_use_ab=None,
        chain_partitions_do_not_use_ab=None, rollback_index=parent.rollback_index, flags=parent.flags,
        rollback_index_location=parent.rollback_index_location, props=None, props_from_file=None,
        kernel_cmdlines=None, setup_rootfs_from_kernel=None, ht_desc_to_setup=None,
        include_descriptors_from_image=None, signing_helper=None, signing_helper_with_files=None,
        release_string=parent.release_string, append_to_release_string=None,
        required_libavb_version_minor=parent.required_libavb_version_minor)
    size = (source/'vbmeta.img').stat().st_size
    assert len(blob) <= size
    (images/'vbmeta.img').write_bytes(blob+b'\0'*(size-len(blob)))
    for path in source.glob('*.img'):
        if path.name not in ('boot.img', 'vbmeta.img'):
            (images/path.name).symlink_to(path.resolve(strict=True))
    run([host/'avbtool', 'verify_image', '--image', images/'vbmeta.img',
         '--follow_chain_partitions'], 'verify-avb-chain', timeout=1800)
    _, final_header, final_descriptors, _ = parse(images/'vbmeta.img')
    assert (parent.flags, parent.rollback_index, parent.rollback_index_location) == (
        final_header.flags, final_header.rollback_index, final_header.rollback_index_location)
    assert [d.encode() for d in new] == [d.encode() for d in final_descriptors]
    package.update(updated_utc=datetime.now(timezone.utc).isoformat(), images=str(images),
                   parent_package=str(args.package.resolve()), parent_package_sha256=sha(args.package),
                   changed_partitions=['boot', 'vbmeta'], boot_verified=False, flashed=False,
                   diagnostic_return_to_bootloader_seconds=(0 if args.preserve_rawdump else args.timeout),
                   rawdump_writer_enabled=not args.preserve_rawdump,
                   boot_cmdline_before=before, boot_cmdline_after=after,
                   kernel_and_ramdisk_unchanged=True, other_avb_descriptors_unchanged=True)
    for name, row in package['new_images'].items():
        path = images/(name+'.img')
        package['new_images'][name] = dict(path=str(path), size=path.stat().st_size, sha256=sha(path))
    (out/'package.json').write_text(json.dumps(package, indent=2)+'\n')
    print(json.dumps(dict(passed=True, package=str(out/'package.json'), timeout=args.timeout,
                         changed_partitions=['boot', 'vbmeta'])))


if __name__ == '__main__':
    main()
