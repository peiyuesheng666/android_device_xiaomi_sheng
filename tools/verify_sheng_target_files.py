#!/usr/bin/env python3
"""Verify a completed normal target-files package and its matching sheng images."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import zipfile

PARTITIONS = {'boot', 'dtbo', 'init_boot', 'odm', 'product', 'recovery', 'system',
              'system_dlkm', 'system_ext', 'vbmeta', 'vbmeta_system', 'vendor',
              'vendor_boot', 'vendor_dlkm'}
DYNAMIC = {'odm', 'product', 'system', 'system_dlkm', 'system_ext', 'vendor', 'vendor_dlkm'}


def digest(stream):
    hasher = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        hasher.update(block)
    return hasher.hexdigest()


def sha(path):
    with path.open('rb') as stream:
        return digest(stream)


def check_build(build):
    status = json.loads((build / 'status.json').read_text())
    if not (status['exit_code'] == 0 and status['normal_module_build_passed']
            and status['postbuild_checks_completed'] and status['last_phase'] == 'complete'
            and 'target-files-package' in status['modules']):
        raise ValueError('A completed normal target-files-package build is required')
    for name in ('prebuild-upstream-audit.json', 'postbuild-upstream-audit.json'):
        audit = json.loads((build / name).read_text())
        if not audit['known_public_sources_passed'] or audit['all_project_nonclean_status']:
            raise ValueError('Failed public-source audit: ' + name)
    for name in ('prebuild-recovery-upstream-audit.json', 'source-mirror.json'):
        if not json.loads((build / name).read_text())['passed']:
            raise ValueError('Failed build check: ' + name)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--build-work', type=Path, required=True)
    parser.add_argument('--target-files', type=Path,
                        help='Default: the normally generated lineage_sheng target-files ZIP')
    parser.add_argument('--images-dir', type=Path,
                        help='Reuse an existing complete image set; every image must exactly match the target-files ZIP')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tmpdir', type=Path, required=True,
                        help='Existing directory with space for releasetools ZIP extraction and APEX activation')
    args = parser.parse_args()
    rom = args.rom.resolve(strict=True)
    build = args.build_work.resolve(strict=True)
    check_build(build)
    product = rom / 'out/target/product/sheng'
    host = rom / 'out/host/linux-x86/bin'
    package = (args.target_files or product / 'obj/PACKAGING/target_files_intermediates/lineage_sheng-target_files.zip').resolve(strict=True)
    temporary = args.tmpdir.resolve(strict=True)
    if not temporary.is_dir():
        raise ValueError('--tmpdir must be an existing directory')
    # Android archives contain relative symlinks and boot character devices.
    # DrvFS can have free space yet reject these operations partway through.
    with tempfile.TemporaryDirectory(prefix='sheng-fs-probe-', dir=temporary) as probe_name:
        probe = Path(probe_name)
        try:
            (probe / 'file').write_bytes(b'sheng')
            (probe / 'link').symlink_to('file')
            if (probe / 'link').read_bytes() != b'sheng':
                raise ValueError('Relative symlink readback failed')
            os.mknod(probe / 'device', stat.S_IFCHR | 0o600, os.makedev(1, 3))
        except OSError as error:
            raise ValueError('--tmpdir must support Linux symlinks and character devices: ' + str(error)) from error
    output_lock = (rom / 'out/.sheng-device-modules.lock').open('a')
    try:
        fcntl.flock(output_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise ValueError('A live build owns the output; wait for terminal completion') from None
    with (host / 'soong_build').open('rb') as compiler:
        restored = compiler.read(4) == b'\x7fELF'
    if (host / 'soong_build.sheng-real').exists() or not restored:
        raise ValueError('The generated Soong compiler has not been restored')
    for tool in ('validate_target_files', 'check_target_files_vintf', 'avbtool', 'img_from_target_files'):
        if not (host / tool).is_file():
            raise ValueError('Missing normal host validation tool: ' + tool)
    work = args.output.resolve()
    work.mkdir(parents=True, exist_ok=False)
    receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), build_work=str(build),
                   target_files=str(package), build_status_sha256=sha(build / 'status.json'),
                   passed=False, full_product_build_passed=False, hardware_tested=False,
                   flashed=False, entire_device_tree_complete=False, images={}, commands=[])
    receipt['validator_source_sha256'] = sha(Path(__file__).resolve())
    receipt['boot_chain_validator_source_sha256'] = sha(Path(__file__).with_name('verify_sheng_boot_chain.py'))
    env = dict(os.environ, PATH=str(host) + os.pathsep + os.environ.get('PATH', ''),
               TMPDIR=str(temporary), LANG='C.UTF-8', LC_ALL='C.UTF-8')

    def run(label, command):
        command = list(map(str, command))
        print('Validation: ' + label, flush=True)
        with (work / (label + '.log')).open('wb') as log:
            result = subprocess.run(command, cwd=rom, env=env, stdout=log, stderr=subprocess.STDOUT)
        receipt['commands'].append(dict(label=label, argv=command, exit_code=result.returncode))
        (work / 'commands.json').write_text(json.dumps(receipt['commands'], indent=2) + '\n')
        result.check_returncode()
        return (work / (label + '.log')).read_text(errors='replace')

    try:
        run('host-tool-source-audit', [rom / 'prebuilts/build-tools/linux-x86/bin/py3-cmd',
                                       Path(__file__).with_name('audit_sheng_releasetools.py'),
                                       '--rom', rom, '--output', work / 'host-tool-source-audit.json'])
        receipt['host_tool_source_audit'] = json.loads((work / 'host-tool-source-audit.json').read_text())
        if not receipt['host_tool_source_audit']['passed']:
            raise ValueError('Host validation tools differ from their selected public source inputs')
        if args.images_dir:
            images = args.images_dir.resolve(strict=True)
            receipt['image_source'] = 'Existing image set verified byte-for-byte against every target-files IMAGES member'
        else:
            image_work = Path(tempfile.mkdtemp(prefix='sheng-packaged-images-', dir=temporary))
            images = image_work / 'images'
            images.mkdir()
            image_zip = image_work / 'images.zip'
            receipt['image_export_zip'] = str(image_zip)
            receipt['image_source'] = 'IMAGES entries exported by normal img_from_target_files; product outputs are comparison evidence only'
            # Releasetools regenerates filesystem images and replaces DTBO AVB
            # footers. A single target-files image set is the authoritative chain.
            run('export-packaged-images', [host / 'img_from_target_files', package, image_zip])
            with zipfile.ZipFile(image_zip) as exported:
                names = exported.namelist()
                if len(names) != len(set(names)):
                    raise ValueError('Duplicate exported image ZIP members')
                for name in sorted(PARTITIONS):
                    with exported.open(name + '.img') as source, (images / (name + '.img')).open('xb') as target:
                        shutil.copyfileobj(source, target)
            receipt['image_export_zip_sha256'] = sha(image_zip)
        receipt['images_dir'] = str(images)
        receipt['kernel_metadata_dir'] = str(product)
        with zipfile.ZipFile(package) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError('Duplicate target-files ZIP members')
            if any(Path(name).is_absolute() or '..' in Path(name).parts for name in names):
                raise ValueError('Unsafe target-files ZIP member path')
            metadata = {name: archive.read('META/' + name) for name in
                        ('misc_info.txt', 'ab_partitions.txt', 'kernel_version.txt', 'kernel_configs.txt')}
            for name, data in metadata.items():
                (work / name).write_bytes(data)
            info = dict(line.split('=', 1) for line in metadata['misc_info.txt'].decode().splitlines()
                        if line and not line.startswith('#') and '=' in line)
            if set(metadata['ab_partitions.txt'].decode().split()) != PARTITIONS:
                raise ValueError('Unexpected A/B partition set')
            if set(info['dynamic_partition_list'].split()) != DYNAMIC or info['vintf_enforce'] != 'true':
                raise ValueError('Missing dynamic partitions or enforced VINTF')
            if info['avb_vbmeta_key_path'] != 'external/avb/test/data/testkey_rsa4096.pem' or \
                    info['avb_vbmeta_system_key_path'] != 'external/avb/test/data/testkey_rsa2048.pem':
                raise ValueError('Review changed AVB key identities before validation')
            if not metadata['kernel_configs.txt'].strip() or metadata['kernel_version.txt'].decode().strip() != \
                    (product / 'obj/KERNEL_OBJ/include/config/kernel.release').read_text().strip():
                raise ValueError('VINTF kernel metadata differs from the built kernel')
            # Releasetools expands the ZIP, and APEX/filesystem processing needs
            # additional scratch space. Reserve before running the validator.
            expanded = sum(member.file_size for member in archive.infolist())
            needed = expanded + sum(archive.getinfo('IMAGES/' + name + '.img').file_size
                                    for name in PARTITIONS) + 5 * 1024**3
            receipt['validation_scratch_required_bytes'] = needed
            if shutil.disk_usage(temporary).free < needed:
                raise ValueError('Insufficient validation scratch space: need ' + str(needed) + ' bytes')
            for name in sorted(PARTITIONS):
                member = 'IMAGES/' + name + '.img'
                image = images / (name + '.img')
                with archive.open(member) as stream:
                    package_hash = digest(stream)
                if image.stat().st_size != archive.getinfo(member).file_size or sha(image) != package_hash:
                    raise ValueError('Exported image differs from target-files IMAGES member: ' + name)
                current = product / (name + '.img')
                current_hash = sha(current)
                receipt.setdefault('product_image_comparison', {})[name] = dict(
                    path=str(current), bytes=current.stat().st_size, sha256=current_hash,
                    identical=current_hash == package_hash)
                with image.open('rb') as stream:
                    header = stream.read(28)
                sparse = header[:4] == b'\x3a\xff\x26\xed'
                logical_size = (struct.unpack_from('<I', header, 12)[0] *
                                struct.unpack_from('<I', header, 16)[0]) if sparse else image.stat().st_size
                receipt['images'][name] = dict(sha256=package_hash, bytes=image.stat().st_size,
                                               sparse=sparse, logical_bytes=logical_size)
            group = info['super_partition_groups'].split()
            if len(group) != 1 or set(info['super_' + group[0] + '_partition_list'].split()) != DYNAMIC:
                raise ValueError('Dynamic super group differs from the packaged partitions')
            dynamic_bytes = sum(receipt['images'][name]['logical_bytes'] for name in DYNAMIC)
            group_bytes = int(info['super_' + group[0] + '_group_size'])
            if not dynamic_bytes <= group_bytes < int(info['super_partition_size']):
                raise ValueError('Dynamic images exceed the declared super group capacity')
            receipt['dynamic_partitions'] = dict(logical_bytes=dynamic_bytes, group_bytes=group_bytes,
                                                  super_bytes=int(info['super_partition_size']))
            receipt['releasetools_file_consistency'] = {
                name: bool(info.get('extfs_sparse_flag') == '-s' and receipt['images'][name]['sparse']
                           and 'IMAGES/' + name + '.map' in names)
                for name in ('system', 'vendor')}
        receipt['target_files_sha256'] = sha(package)
        root_key = rom / info['avb_vbmeta_key_path']
        system_key = rom / info['avb_vbmeta_system_key_path']
        public_key = work / 'vbmeta_system.avbpubkey'
        run('chain-public-key', [host / 'avbtool', 'extract_public_key', '--key', system_key,
                                 '--output', public_key])
        location = info['avb_vbmeta_system_rollback_index_location']
        run('avb-chain', [host / 'avbtool', 'verify_image', '--image', images / 'vbmeta.img',
                          '--key', root_key, '--expected_chain_partition',
                          'vbmeta_system:' + location + ':' + str(public_key)])
        # This avbtool revision propagates --key to a followed child, even
        # when the chain descriptor embeds a different expected public key.
        # Bind the child key/location above, then verify it with its own key.
        run('avb-system', [host / 'avbtool', 'verify_image', '--image', images / 'vbmeta_system.img',
                          '--key', system_key])
        receipt['avb_chain_verification'] = 'Parent signature, exact child key/location, child signature, and all image descriptors with their respective keys'
        covered = set()
        for name in ('vbmeta', 'vbmeta_system'):
            text = run(name + '-info', [host / 'avbtool', 'info_image', '--image', images / (name + '.img')])
            covered.update(re.findall(r'Partition Name:\s+(\S+)', text))
            receipt[name + '_flags'] = int(re.search(r'Flags:\s+(\d+)', text).group(1))
        if covered != PARTITIONS - {'vbmeta'}:
            raise ValueError('AVB descriptors do not cover the complete A/B image set: ' + repr(covered))
        receipt['software_avb_chain_verified'] = True
        receipt['locked_secure_boot_verified'] = False
        run('target-files-validation', [host / 'validate_target_files', package,
                                        '--avb_vbmeta_system_key_path', system_key])
        run('vintf-validation', [host / 'check_target_files_vintf', '-p', host.parent, package])
        run('boot-chain-validation', [sys.executable, Path(__file__).with_name('verify_sheng_boot_chain.py'),
                                      '--rom', rom, '--build-work', build, '--images-dir', images,
                                      '--output', work / 'boot-chain'])
        receipt['boot_chain'] = json.loads((work / 'boot-chain/verification.json').read_text())
        if not receipt['boot_chain']['passed']:
            raise ValueError('Boot/module closure verification did not pass')
        receipt['releasetools_validation_passed'] = True
        receipt['vintf_validation_passed'] = True
        receipt['file_consistency_scope'] = (
            'Upstream per-file comparison requires system/vendor maps; applicable partitions: ' +
            ','.join(name for name, enabled in receipt['releasetools_file_consistency'].items() if enabled) +
            '. Empty means no per-file comparisons are claimed.')
        receipt['full_product_build_passed'] = True
        receipt['passed'] = True
    except Exception as error:
        receipt['error'] = repr(error)
        raise
    finally:
        (work / 'verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps({key: receipt[key] for key in ('passed', 'full_product_build_passed', 'target_files',
                                                       'images_dir', 'error') if key in receipt}, indent=2))


if __name__ == '__main__':
    main()
