#!/usr/bin/env python3
"""Verify normal sheng boot/DLKM images, module CRCs and Recovery contents."""
import argparse
import hashlib
import json
from pathlib import Path
import stat
import struct
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--rom', type=Path, required=True)
parser.add_argument('--build-work', type=Path, required=True)
parser.add_argument('--full-build-event', type=Path,
                    help='Completion event and build evidence from a complete ROM target')
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--product-out', type=Path,
                    help='Saved product images and matching kernel metadata; default: ROM output')
parser.add_argument('--images-dir', type=Path,
                    help='Coherent packaged image set; kernel and recovery build metadata stay in --product-out')
args = parser.parse_args()
ROM = args.rom.resolve(strict=True)
SOURCE = Path(__file__).resolve().parents[1]
PRODUCT = (args.product_out or ROM / 'out/target/product/sheng').resolve(strict=True)
IMAGES = (args.images_dir or PRODUCT).resolve(strict=True)
HOST = ROM / 'out/host/linux-x86/bin'
OUT = args.output.resolve()
OUT.mkdir(parents=True, exist_ok=False)
build = args.build_work.resolve(strict=True)
if args.full_build_event:
    event = json.loads(args.full_build_event.read_text())
    assert event['state'] == 'finished' and event['succeeded'] and event['returncode'] == 0
    assert event['phase'] == 'compiled', 'The complete ROM target did not finish'
    assert json.loads((build / 'event.json').read_text()) == event
    for name in ('device-source-mirror-prebuild.json', 'device-source-mirror-postbuild.json'):
        mirror = json.loads((build / name).read_text())
        assert mirror['passed'] and Path(mirror['rom']).resolve() == ROM
    for name in ('prebuild-upstream-source-audit.json', 'postbuild-upstream-source-audit.json'):
        audit = json.loads((build / name).read_text())
        assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
else:
    status = json.loads((build / 'status.json').read_text())
    assert status['normal_module_build_passed'] and status['postbuild_checks_completed']
    expected_targets = {'bootimage', 'vendorbootimage', 'initbootimage', 'recoveryimage',
                        'dtboimage', 'vendor_dlkmimage', 'system_dlkmimage'}
    assert (expected_targets <= set(status['modules']) or
            'target-files-package' in status['modules']), 'Incomplete normal image build scope'
    assert json.loads((build / 'source-mirror.json').read_text())['passed']
    for name in ('prebuild-upstream-audit.json', 'postbuild-upstream-audit.json'):
        audit = json.loads((build / name).read_text())
        assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
    assert json.loads((build / 'prebuild-recovery-upstream-audit.json').read_text())['passed']
sys.path.insert(0, str(SOURCE / 'interfaces/kernel/stock-modules'))
from stage import Module


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(command, label):
    result = subprocess.run(list(map(str, command)), capture_output=True)
    if '-dc' not in command:
        (OUT / (label + '.log')).write_bytes(result.stdout + result.stderr)
    result.check_returncode()
    return result.stdout


def cpio(path):
    raw = run([HOST / 'lz4', '-dc', path], path.parent.name + '-' + path.name)
    entries = {}
    offset = 0
    while offset + 110 <= len(raw):
        if raw[offset:offset + 6] != b'070701':
            assert not raw[offset:].strip(b'\0'), (path, offset)
            break
        fields = [int(raw[offset + 6 + i * 8:offset + 14 + i * 8], 16) for i in range(13)]
        mode, size, namesize = fields[1], fields[6], fields[11]
        name = raw[offset + 110:offset + 110 + namesize - 1].decode().removeprefix('./')
        assert not Path(name).is_absolute() and '..' not in Path(name).parts, name
        offset = (offset + 110 + namesize + 3) & ~3
        data = raw[offset:offset + size]
        assert len(data) == size
        offset = (offset + size + 3) & ~3
        if name != 'TRAILER!!!':
            if name in entries:
                assert entries[name] == (mode, data), (name, 'conflicting archive entries')
            entries[name] = (mode, data)
    return entries


def module_name(name):
    return Path(name).name.removesuffix('.ko').replace('-', '_')


def load_list(data):
    return [module_name(line.strip()) for line in data.decode().splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


def module_map(entries):
    result = {}
    for name, (mode, data) in entries.items():
        if name.startswith('lib/modules/') and name.endswith('.ko'):
            assert stat.S_ISREG(mode)
            key = module_name(name)
            assert key not in result
            result[key] = data
    return result


archives = {}
report = {'images': {}, 'build_work': str(build), 'flashed': False, 'hardware_tested': False,
          'full_product_build_passed': bool(args.full_build_event), 'images_dir': str(IMAGES),
          'kernel_metadata_dir': str(PRODUCT)}
for name in ('boot', 'vendor_boot', 'init_boot', 'recovery', 'dtbo', 'vendor_dlkm', 'system_dlkm'):
    path = IMAGES / (name + '.img')
    data = path.read_bytes()
    info = run([HOST / 'avbtool', 'info_image', '--image', path], name + '-avb-info').decode()
    run([HOST / 'avbtool', 'verify_image', '--image', path], name + '-avb-verify')
    assert 'Partition Name:        ' + name in info
    report['images'][name] = {'sha256': sha(data), 'size': len(data), 'avb_hash_verified': True}
    if name not in ('boot', 'vendor_boot', 'init_boot', 'recovery'):
        continue
    parts = OUT / name
    header = run([HOST / 'unpack_bootimg', '--boot_img', path, '--out', parts], name + '-header').decode()
    report['images'][name]['header'] = header
    if name == 'vendor_boot':
        ramdisks = sorted(parts.glob('vendor_ramdisk[0-9]*'))
        assert ramdisks
        assert data[:8] == b'VNDRBOOT' and struct.unpack_from('<I', data, 8)[0] == 4
    else:
        assert data[:8] == b'ANDROID!' and struct.unpack_from('<I', data, 40)[0] == 4
        kernel_size, ramdisk_size = struct.unpack_from('<II', data, 8)
        report['images'][name].update(kernel_size=kernel_size, ramdisk_size=ramdisk_size)
        if name == 'boot':
            assert kernel_size and not ramdisk_size
            assert (parts / 'kernel').read_bytes() == (PRODUCT / 'kernel').read_bytes()
            assert (parts / 'kernel').read_bytes() == (
                PRODUCT / 'obj/KERNEL_OBJ/arch/arm64/boot/Image').read_bytes()
        else:
            assert not kernel_size and ramdisk_size
        ramdisks = [parts / 'ramdisk']
    merged = {}
    for ramdisk in ramdisks:
        if ramdisk.is_file() and ramdisk.stat().st_size:
            merged.update(cpio(ramdisk))
    archives[name] = merged

# Bootloader prepends recovery, then appends vendor and generic ramdisks.
recovery = archives['recovery'] | archives['vendor_boot'] | archives['init_boot']
normal = archives['vendor_boot'] | archives['init_boot']
for label, entries, expected in (
        ('normal', normal, 'modules.load.first_stage'),
        ('recovery', recovery, 'modules.load.recovery')):
    modules = module_map(entries)
    selected = ('lib/modules/modules.load.recovery' if label == 'recovery'
                and 'lib/modules/modules.load.recovery' in entries else 'lib/modules/modules.load')
    actual = load_list(entries[selected][1])
    required = load_list((SOURCE / 'configs/modules' / expected).read_bytes())
    assert actual == required, (label, 'wrong load order')
    assert len(actual) == len(set(actual))
    assert not (set(actual) - modules.keys()), (label, 'missing module')
    if label == 'recovery':
        assert 'block2mtd' not in actual and 'block2mtd' in modules
    report[label + '_modules'] = {'count': len(modules), 'load_count': len(actual),
                                'selected_load_file': selected, 'load_order_matches_source': True}

for relative, installed in (
        ('rootdir/etc/init.recovery.qcom.rc', 'system/etc/init/init.recovery.qcom.rc'),
        ('rootdir/recovery/hardware.sh', 'system/bin/sheng-recovery-hardware'),
        ('rootdir/recovery/late-modules.sh', 'system/bin/sheng-recovery-late-modules'),
        ('rootdir/recovery/init.recovery.sheng-late-modules.rc', 'system/etc/init/init.recovery.sheng-late-modules.rc'),
        ('rootdir/recovery/touch.sh', 'system/bin/sheng-recovery-touch'),
        ('rootdir/recovery/init.recovery.sheng-touch.rc', 'system/etc/init/init.recovery.sheng-touch.rc')):
    assert recovery[installed][1] == (SOURCE / relative).read_bytes(), installed
touch = json.loads((SOURCE / 'rootdir/recovery/touch-inputs.json').read_text())
for entry in touch['entries']:
    assert sha(recovery[entry['installed']][1]) == entry['sha256'], entry['installed']
assert stat.S_ISLNK(recovery['odm/firmware'][0])
assert recovery['odm/firmware'][1] == b'/vendor/odm/firmware'
for service in ('sheng-recovery-touch', 'sheng-recovery-hardware', 'sheng-recovery-late-modules'):
    count = sum(line.startswith('service ' + service + ' ')
                for name, (_, data) in recovery.items() if name.endswith('.rc')
                for line in data.decode().splitlines())
    assert count == 1, (service, count)
for name in ('sepolicy', 'system/lib64/librecovery_ui_ext.so'):
    assert recovery[name][1] == (PRODUCT / 'recovery/root' / name).read_bytes()

# Read the actual DLKM filesystems, then check every import CRC against this
# kernel and these modules. Never modify module versions or import metadata.
vendor = OUT / 'vendor_dlkm-root'
system = OUT / 'system_dlkm-root'
vendor.mkdir()
system.mkdir()
def filesystem_image(name):
    image = IMAGES / (name + '.img')
    with image.open('rb') as stream:
        sparse = stream.read(4) == b'\x3a\xff\x26\xed'
    if sparse:
        raw = OUT / (name + '-raw.img')
        run([HOST / 'simg2img', image, raw], name + '-unsparse')
        return raw
    return image

run([HOST / 'fsck.erofs', '--extract=' + str(vendor), filesystem_image('vendor_dlkm')], 'vendor-dlkm-extract')
run([HOST / 'debugfs', '-R', 'rdump / ' + str(system), filesystem_image('system_dlkm')], 'system-dlkm-extract')
all_modules = {}
for root in (vendor, system):
    paths = sorted(root.rglob('*.ko'))
    assert paths
    for path in paths:
        name = module_name(path.name)
        assert name not in all_modules, name
        all_modules[name] = Module(path)
kernel = PRODUCT / 'obj/KERNEL_OBJ'
release = (kernel / 'include/config/kernel.release').read_text().strip()
assert release.startswith('5.15.'), 'The retained BSP audit is scoped to 5.15'
config = (kernel / '.config').read_text().splitlines()
assert 'CONFIG_MODVERSIONS=y' in config and 'CONFIG_MODULE_FORCE_LOAD=y' not in config
exports = {}
for line in (kernel / 'Module.symvers').read_text().splitlines():
    crc, name, owner, *_ = line.split()
    if owner == 'vmlinux':
        exports[name] = (int(crc, 16), owner)
for name, module in all_modules.items():
    for symbol, crc in module.exports().items():
        assert symbol not in exports, (name, 'duplicate export', symbol)
        exports[symbol] = (crc, name)
flags = all_modules['zram'].info['vermagic'].split()[1:]
imports = 0
for name, module in all_modules.items():
    assert module.info['vermagic'].split()[1:] == flags, (name, 'vermagic flags')
    assert module.info['vermagic'].split()[0].startswith('5.15.'), name
    for symbol, crc in module.imports().items():
        assert symbol in exports, (name, 'unresolved', symbol)
        assert exports[symbol][0] == crc, (name, 'CRC mismatch', symbol)
        imports += 1
ramdisk_closures = {}
for label, entries in (('normal', normal), ('recovery', recovery)):
    packaged = module_map(entries)
    dep_entries = {}
    for line in entries['lib/modules/modules.dep'][1].decode().splitlines():
        owner, dependencies = line.split(':', 1)
        owner = module_name(owner)
        assert owner not in dep_entries
        dep_entries[owner] = [module_name(value) for value in dependencies.split()]
    assert set(dep_entries) == set(packaged), (label, 'incomplete modules.dep')
    for owner, dependencies in dep_entries.items():
        assert not (set(dependencies) - packaged.keys()), (label, owner, 'missing dependency')
    checked = 0
    for name in packaged:
        for symbol in all_modules[name].imports():
            provider = exports[symbol][1]
            assert provider == 'vmlinux' or provider in packaged, (label, name, symbol, provider)
            checked += 1
    ramdisk_closures[label] = {'modules': len(packaged), 'symbol_providers_checked': checked,
                               'modules_dep_complete': True}
signature_checks = {}
for label, entries in archives.items():
    for name, data in module_map(entries).items():
        dlkm_data = all_modules[name].data
        if data == dlkm_data:
            continue
        # Lineage signs source GKI modules only in system_dlkm. Require the
        # exact same ELF payload and a signature from this kernel's own key.
        assert name in ('zram', 'zsmalloc'), (label, name, 'ramdisk/DLKM mismatch')
        magic = b'~Module signature appended~\n'
        assert dlkm_data.endswith(magic)
        metadata = dlkm_data[-len(magic)-12:-len(magic)]
        assert metadata[:8] == bytes([0, 0, 2, 0, 0, 0, 0, 0])
        signature_size = struct.unpack('>I', metadata[8:])[0]
        payload_size = len(dlkm_data) - len(magic) - 12 - signature_size
        assert dlkm_data[:payload_size] == data, (label, name, 'different ELF payload')
        if name in signature_checks:
            continue
        signature = OUT / (name + '-signature.der')
        signature.write_bytes(dlkm_data[payload_size:payload_size + signature_size])
        payload = OUT / (name + '-signed-payload.ko')
        payload.write_bytes(data)
        certificate = OUT / 'kernel-signing-certificate.pem'
        run(['openssl', 'x509', '-inform', 'DER', '-in', kernel / 'certs/signing_key.x509',
             '-out', certificate], 'kernel-certificate')
        run(['openssl', 'cms', '-verify', '-binary', '-inform', 'DER', '-in', signature,
             '-content', payload, '-nointern', '-certfile', certificate, '-noverify',
             '-out', '/dev/null'], name + '-signature-verification')
        signature_checks[name] = {'elf_payload_identical': True, 'signature_verified': True,
                                 'kernel_certificate_sha256': sha(certificate.read_bytes())}
compatibility = json.loads((kernel / 'sheng-stock-module-compatibility.json').read_text())
assert compatibility['errors'] == []
assert len(all_modules) == compatibility['effective_modules_checked']
report['module_abi'] = {'release': release, 'modules': len(all_modules),
                        'import_crcs_checked': imports, 'modversions': True,
                        'force_load': False, 'ramdisk_module_elf_payloads_match_dlkm': True,
                        'system_dlkm_signature_checks': signature_checks}
report['ramdisk_dependency_closures'] = ramdisk_closures
report['recovery_sources_and_touch_hashes_match'] = True
report['passed'] = True
(OUT / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({key: value for key, value in report.items() if key != 'images'}, indent=2))
