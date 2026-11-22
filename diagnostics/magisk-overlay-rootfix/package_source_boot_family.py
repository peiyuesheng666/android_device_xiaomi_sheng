#!/usr/bin/env python3
"""Offline boot-family packaging from pinned live parents and full source outputs.

This never connects to a device. DLKM/system/policy/root-vbmeta integration and
runtime qualification are deliberately NOT implied by a successful receipt.
"""
import argparse
import hashlib
import importlib.util
import json
import lzma
import shutil
from pathlib import Path
import stat
import subprocess
import sys

from export_source_built_binaries import check_static_elf
from storage_guard import require_build_space

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[4]
sys.path.insert(0, str(WORKSPACE / 'scripts'))
sys.path.insert(0, str(HERE.parents[1] / 'tools'))
from build_sheng_fastbootd_cold_trace import parse_cpio, sha
from package_sheng_recovery_modules import replace_records
from sheng_kernel_image import qualify as qualify_kernel_image


def inventory(plain):
    return {e['name']: e for e in parse_cpio(plain)[0]}


def module_replacements(plain, staged, *, recovery=False):
    entries = inventory(plain)
    modules = {name for name in entries if name.startswith('lib/modules/') and name.endswith('.ko')}
    expected = {'lib/modules/' + p.name for p in staged.glob('*.ko')}
    if not expected or modules != expected:
        raise ValueError('Parent module providers differ from the qualified source ramdisk')
    names = modules | {name for name in entries if name.startswith('lib/modules/modules.')}
    replacements = {}
    for name in sorted(names):
        e = entries[name]
        if not stat.S_ISREG(e['fields'][1]) or e['fields'][4] != 1:
            raise ValueError('Expected regular single-linked module or loader metadata')
        source = staged / Path(name).name
        if recovery and name == 'lib/modules/modules.load':
            source = staged / 'modules.load.recovery'
        if source.is_symlink() or not source.is_file():
            raise ValueError('Unrecognized module metadata: ' + name)
        replacements[name] = source.read_bytes()
    return replacements


def init_replacement(plain, executable):
    entries = inventory(plain)
    backup = entries.get('.backup/init.xz')
    if backup is None or not stat.S_ISREG(backup['fields'][1]) or backup['fields'][4] != 1:
        raise ValueError('Expected existing Magisk original-init backup')
    check_static_elf(lzma.decompress(backup['payload']))
    check_static_elf(executable)
    result = lzma.compress(executable, preset=9, check=lzma.CHECK_CRC32)
    if lzma.decompress(result) != executable:
        raise ValueError('XZ roundtrip failed')
    return {'.backup/init.xz': result}


def validate_bootlog_policy(config, audit, *, diagnostic=False, release_pystore=False):
    if diagnostic and release_pystore:
        raise ValueError('Diagnostic and release pystore modes are mutually exclusive')
    enabled = 'CONFIG_SHENG_BOOTLOG=y' in config.splitlines()
    disabled = '# CONFIG_SHENG_BOOTLOG is not set' in config.splitlines()
    if enabled == disabled or audit.get('bootlog_disabled') is not disabled:
        raise ValueError('Actual bootlog config and audited mode disagree')
    if diagnostic or release_pystore:
        if not (enabled and audit.get('diagnostic_only') is diagnostic and
                audit.get('logger_identity_verified_in_object_and_vmlinux') is True and
                'CONFIG_LOG_BUF_SHIFT=22' in config.splitlines()):
            raise ValueError('Enabled logger requires explicit linked-logger qualification')
        if release_pystore and (audit.get('diagnostic_only') is not False or
                audit.get('pystore_boot_only_verified_in_object_and_vmlinux') is not True):
            raise ValueError('Release pystore requires non-diagnostic boot-only qualification')
    elif not disabled:
        raise ValueError('Release boot-family packaging requires compiled-out bootlog')


def preserve_rawdump_cmdline(cmdline):
    words = cmdline.split()
    for key in ('sheng_bootlog.enable', 'sheng_bootlog.test_timeout'):
        if sum(w.startswith(key + '=') for w in words) > 1:
            raise ValueError('Ambiguous diagnostic command line: ' + key)
    words = ['sheng_bootlog.enable=0' if w.startswith('sheng_bootlog.enable=') else
             'sheng_bootlog.test_timeout=0' if w.startswith('sheng_bootlog.test_timeout=') else w
             for w in words]
    if 'sheng_bootlog.enable=0' not in words:
        words.append('sheng_bootlog.enable=0')
    return ' '.join(words)


def release_pystore_cmdline(cmdline, *, recording):
    words = preserve_rawdump_cmdline(cmdline).split()
    # Never inherit stage holds, reset deadlines or a pre-latched stop flag.
    for key in ('sheng_bootlog.pre_driver_hold_ms', 'sheng_bootlog.boot_complete'):
        if sum(w.startswith(key + '=') for w in words) > 1:
            raise ValueError('Ambiguous release command line: ' + key)
        words = [w for w in words if not w.startswith(key + '=')]
    words = [w for w in words if not w.startswith('sheng_bootlog.test_timeout=')]
    words = ['sheng_bootlog.enable=1' if recording and w == 'sheng_bootlog.enable=0' else w
             for w in words]
    words.append('sheng_bootlog.test_timeout=0')
    return ' '.join(words)


def kernel_arguments(name, before, kernel, *, diagnostic=False, release_pystore=False,
                     recovery_embeds_kernel=None, preserve_rawdump=False):
    if diagnostic and release_pystore:
        raise ValueError('Diagnostic and release pystore modes are mutually exclusive')
    argv = before.copy()
    changed = False
    if name in ('boot', 'recovery'):
        if argv.count('--kernel') != 1:
            raise ValueError('Expected exactly one kernel in boot and Recovery')
        if name == 'recovery' and recovery_embeds_kernel is None:
            raise ValueError('Recovery embedded/shared kernel layout must be inspected explicitly')
        if name == 'boot' or recovery_embeds_kernel:
            argv[argv.index('--kernel') + 1] = str(kernel)
        if diagnostic or release_pystore or preserve_rawdump:
            if argv.count('--cmdline') != 1:
                raise ValueError('Expected exactly one diagnostic command line')
            index = argv.index('--cmdline') + 1
            argv[index] = (release_pystore_cmdline(argv[index], recording=name == 'boot' and not preserve_rawdump)
                           if release_pystore or preserve_rawdump else preserve_rawdump_cmdline(argv[index]))
            changed = argv[index] != before[index]
    return argv, changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['rom', 'parents', 'parent-manifest', 'kernel-audit', 'module-stage', 'kernel', 'work', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    init_mode = parser.add_mutually_exclusive_group(required=True)
    init_mode.add_argument('--binary-export', type=Path)
    init_mode.add_argument('--preserve-init', action='store_true',
                           help='Copy pinned init_boot byte-for-byte; do not replace init or claim a new init build')
    parser.add_argument('--diagnostic-kernel', action='store_true',
                        help='Require explicitly audited linked logger; preserve rawdump in BOTH boot and Recovery')
    parser.add_argument('--release-pystore', action='store_true',
                        help='Require audited release boot-only pystore; Recovery preserves logs; no reset timer')
    parser.add_argument('--preserve-rawdump', action='store_true',
                        help='Use audited release pystore with recording disabled in boot and Recovery')
    args = parser.parse_args()
    if sum((args.diagnostic_kernel, args.release_pystore, args.preserve_rawdump)) > 1:
        parser.error('Choose diagnostic or release pystore, not both')
    rom = args.rom.resolve(strict=True)
    parents = args.parents.resolve(strict=True)
    stage = args.module_stage.resolve(strict=True)
    kernel = args.kernel.resolve(strict=True)
    export = args.binary_export.resolve(strict=True) if args.binary_export else None
    work, out = args.work.resolve(), args.out.resolve()
    if out.exists() or work.exists():
        parser.error('Preserve previous candidates: both work and out must be new')
    storage = require_build_space(work, minimum_output=2 * 1024**3, minimum_host=2 * 1024**3)
    storage += require_build_space(out, minimum_output=1024**3, minimum_host=2 * 1024**3)
    pinned = json.loads(args.parent_manifest.read_text())
    audit = json.loads(args.kernel_audit.read_text())
    prepared = json.loads((stage / 'prepared.json').read_text())
    final_image = qualify_kernel_image(Path(prepared['final_kernel_out']),
        Path('/root/sheng-pixelos/diagnostics/kernel618-android-deps/prebuilts/clang/host/linux-x86/clang-r584948c/bin/llvm-objcopy'))
    assert final_image == prepared['final_kernel_image']
    assert sha(kernel) == final_image['kernel_image_sha256']
    assert audit['passed'] and prepared['module_count'] == 474
    validate_bootlog_policy((Path(prepared['final_kernel_out'])/'.config').read_text(), audit,
                           diagnostic=args.diagnostic_kernel,
                           release_pystore=args.release_pystore or args.preserve_rawdump)
    assert sha(stage / 'prepared.json') == audit['prepared_sha256']
    assert sha(kernel) == prepared['kernel_image_sha256'] == audit['core']['arch/arm64/boot/Image']
    init = None
    if export is not None:
        binaries = json.loads((export / 'qualification.json').read_text())
        assert binaries['passed'] and binaries['scope'] == 'audited binary export only'
        init = export / 'first-stage-init/init'
        iq = json.loads((init.parent / 'qualification.json').read_text())
        assert iq['passed'] and not iq['test_only'] and iq['build_mode'] == 'actual-current-product-source'
        assert sha(init) == iq['binary_sha256'] == binaries['binaries']['init']['sha256']
    for name, row in prepared['modules'].items():
        assert all(row[k] for k in ['btf_unchanged', 'imports_crc_unchanged', 'exports_crc_unchanged', 'signature_verified']), name
        assert sha(stage / 'modules' / row['filename']) == row['packaged_sha256'], name
    for p in (stage / 'vendor_ramdisk/lib/modules').glob('*.ko'):
        assert sha(p) == sha(stage / 'modules' / p.name), p
    assert set(pinned) == {'boot', 'vendor_boot', 'init_boot', 'recovery'}
    for name, row in pinned.items():
        path = parents / (name + '.img')
        assert path.stat().st_size == row['bytes'] and sha(path) == row['sha256'], name

    work.mkdir(parents=True)
    out.mkdir(parents=True)
    images = out / 'images'; images.mkdir()
    logs = out / 'logs'; logs.mkdir()
    avbpath = rom / 'external/avb/avbtool.py'
    spec = importlib.util.spec_from_file_location('source_family_avb', avbpath)
    avb = importlib.util.module_from_spec(spec); spec.loader.exec_module(avb)
    commands = []

    def run(argv, label, data=None):
        p = subprocess.run(list(map(str, argv)), input=data, capture_output=True, timeout=180)
        (logs / (label + '.stdout')).write_bytes(p.stdout)
        (logs / (label + '.stderr')).write_bytes(p.stderr)
        commands.append(dict(label=label, argv=list(map(str, argv)), returncode=p.returncode))
        (out / 'commands.json').write_text(json.dumps(commands, indent=2))
        if p.returncode:
            raise RuntimeError(label + ' failed; see logs')
        return p.stdout

    def info(path):
        handler = avb.ImageHandler(str(path), read_only=True)
        try:
            return avb.Avb()._parse_image(handler)
        finally:
            handler._image.close()

    def unpack(path, folder, label):
        raw = run([sys.executable, rom / 'system/tools/mkbootimg/unpack_bootimg.py', '--boot_img', path,
                   '--out', folder, '--format', 'mkbootimg', '-0'], label)
        assert raw.endswith(b'\0')
        return [v.decode() for v in raw[:-1].split(b'\0')]

    results = {}
    for name, pin in pinned.items():
        parent = parents / (name + '.img')
        run([sys.executable, avbpath, 'verify_image', '--image', parent], name + '-parent-avb')
        if name == 'init_boot' and args.preserve_init:
            image = images / 'init_boot.img'
            shutil.copyfile(parent, image)
            assert sha(image) == pin['sha256'] and image.stat().st_size == pin['bytes']
            run([sys.executable, avbpath, 'verify_image', '--image', image], name + '-verify')
            results[name] = dict(path=str(image), bytes=image.stat().st_size,
                                 sha256=sha(image), parent_sha256=pin['sha256'],
                                 copied_byte_identical=True, changed_records=[],
                                 kernel_replaced=False, standalone_avb_verified=True)
            continue
        before_dir = work / (name + '-before')
        before = unpack(parent, before_dir, name + '-unpack')
        recovery_embeds_kernel = (name == 'recovery' and (before_dir/'kernel').stat().st_size > 0)
        argv, commandline_changed = kernel_arguments(name, before, kernel, diagnostic=args.diagnostic_kernel,
                                                    release_pystore=args.release_pystore,
                                                    recovery_embeds_kernel=recovery_embeds_kernel,
                                                    preserve_rawdump=args.preserve_rawdump)
        replacements, packed, ramdisk = {}, None, None
        if name == 'boot':
            cmdline = argv[argv.index('--cmdline') + 1].split()
            wanted = '1' if args.release_pystore else '0'
            assert 'sheng_bootlog.enable=' + wanted in cmdline
            assert 'sheng_bootlog.enable=' + ('0' if args.release_pystore else '1') not in cmdline
            argv[argv.index('--kernel') + 1] = str(kernel)
        else:
            flag = '--vendor_ramdisk_fragment' if name == 'vendor_boot' else '--ramdisk'
            assert argv.count(flag) == 1, 'Unknown multi-fragment layout'
            ramdisk = Path(argv[argv.index(flag) + 1])
            plain = run(['lz4', '-dc', ramdisk], name + '-decompress')
            if name == 'init_boot':
                replacements = init_replacement(plain, init.read_bytes())
            else:
                replacements = module_replacements(plain, stage / 'vendor_ramdisk/lib/modules', recovery=name == 'recovery')
                if name == 'vendor_boot':
                    assert b'overlay=off' not in inventory(plain)['system/etc/fstab.qcom']['payload']
            packed = replace_records(plain, replacements, parse_cpio)
            compressed = work / (name + '-ramdisk.lz4')
            compressed.write_bytes(run(['lz4', '-l', '-9', '-c'], name + '-compress', packed))
            argv[argv.index(flag) + 1] = str(compressed)
        image = images / (name + '.img')
        run([sys.executable, rom / 'system/tools/mkbootimg/mkbootimg.py', *argv,
             '--vendor_boot' if name == 'vendor_boot' else '--output', image], name + '-pack')
        _, header, descriptors, _ = info(parent)
        hashes = [d for d in descriptors if isinstance(d, avb.AvbHashDescriptor)]
        assert header.algorithm_type == 0 and len(hashes) == 1 and hashes[0].partition_name == name
        desc = hashes[0]
        footer = [sys.executable, avbpath, 'add_hash_footer', '--image', image, '--partition_size', parent.stat().st_size,
                  '--partition_name', name, '--algorithm', 'NONE', '--salt', desc.salt.hex(), '--hash_algorithm', desc.hash_algorithm,
                  '--flags', header.flags, '--rollback_index', header.rollback_index, '--rollback_index_location', header.rollback_index_location]
        for d in descriptors:
            if isinstance(d, avb.AvbPropertyDescriptor):
                footer += ['--prop', d.key + ':' + d.value.decode()]
            else:
                assert isinstance(d, avb.AvbHashDescriptor)
        run(footer, name + '-footer')
        run([sys.executable, avbpath, 'verify_image', '--image', image], name + '-verify')
        _, new_header, new_desc, _ = info(image)
        assert vars(header) == vars(new_header)
        properties = lambda ds: [d.encode() for d in ds if not isinstance(d, avb.AvbHashDescriptor)]
        assert properties(descriptors) == properties(new_desc)
        after_dir = work / (name + '-after')
        after = unpack(image, after_dir, name + '-readback')
        normalize = lambda values, folder: ['PART/' + Path(x).name if x.startswith(str(folder) + '/') else x for x in values]
        expected_header = before.copy()
        if commandline_changed:
            expected_header[expected_header.index('--cmdline') + 1] = argv[argv.index('--cmdline') + 1]
        assert normalize(expected_header, before_dir) == normalize(after, after_dir)
        for p in before_dir.iterdir():
            if not p.is_file():
                continue
            if (name == 'boot' or recovery_embeds_kernel) and p.name == 'kernel':
                assert sha(after_dir / p.name) == sha(kernel)
            elif ramdisk is not None and p == ramdisk:
                assert run(['lz4', '-dc', after_dir / p.name], name + '-verify-cpio') == packed
            else:
                assert sha(p) == sha(after_dir / p.name), p
        assert image.stat().st_size == pin['bytes'] and sha(parent) == pin['sha256']
        results[name] = dict(path=str(image), bytes=image.stat().st_size, sha256=sha(image),
                             parent_sha256=pin['sha256'], changed_records=sorted(replacements),
                             kernel_replaced=name == 'boot' or recovery_embeds_kernel,
                             kernel_source=('embedded' if name == 'boot' or recovery_embeds_kernel else
                                            'boot-shared' if name == 'recovery' else 'none'),
                             standalone_avb_verified=True,
                             commandline_changed=commandline_changed,
                             unchanged_header_dtb_bootconfig_and_records_verified=not commandline_changed,
                             unchanged_header_except_explicit_cmdline_verified=True)
    result = dict(passed=True, scope='offline boot-family only', images=results,
                  storage_preflight=storage, kernel_sha256=sha(kernel), init_sha256=sha(init) if init else None,
                  init_boot_preserved_byte_identical=args.preserve_init,
                  module_stage_receipt_sha256=sha(stage / 'prepared.json'),
                  kernel_audit_sha256=sha(args.kernel_audit), binary_export_receipt_sha256=sha(export / 'qualification.json') if export else None,
                  ramdisk_modules_per_image=343, magisk_binary_unchanged=True,
                  kernel_bootlog_disabled=not (args.diagnostic_kernel or args.release_pystore or args.preserve_rawdump),
                  release_pystore=args.release_pystore,
                  diagnostic_kernel=args.diagnostic_kernel,
                  preserve_rawdump_cmdlines_requested_in_boot_and_recovery=args.diagnostic_kernel or args.preserve_rawdump,
                  original_parents_unchanged=True,
                  dlkm_integration_verified=False, policy_system_integration_verified=False,
                  full_avb_chain_verified=False, deployable_combination=False,
                  rawdump_preservation_runtime_verified=False, runtime_verified=False, flashed=False)
    (out / 'qualification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
