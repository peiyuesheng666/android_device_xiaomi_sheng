#!/usr/bin/env python3
"""Offline DP lane-retry module pair; retain current USB/Recovery policy records.

No device access, flash, role change or reboot. Qualification is not DP acceptance.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

def check_imports(module, providers):
    """Require versioned module_layout and unique matching actual providers."""
    imports = module.versions()
    assert 'module_layout' in imports, 'Missing module_layout CRC'
    for symbol, crc in imports.items():
        assert len(providers.get(symbol, [])) == 1, ('missing/duplicate provider', symbol)
        assert providers[symbol][0][1] == crc, ('CRC mismatch', symbol)
    assert module.undefined() <= set(providers), sorted(module.undefined() - set(providers))
    return sorted(module.undefined() - set(imports))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--installed-pair', type=Path, required=True)
    parser.add_argument('--current-boot', type=Path, required=True)
    parser.add_argument('--current-boot-sha256', required=True)
    parser.add_argument('--module', type=Path, required=True)
    parser.add_argument('--diagnostic-root', type=Path, required=True)
    parser.add_argument('--module-qualification', type=Path, required=True)
    args = parser.parse_args()
    w = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(w/'scripts'))
    from build_sheng_fastbootd_cold_trace import sha, digest, parse_cpio
    a = Path('/root/sheng-pixelos/android')
    sys.path.insert(0, str(w/'device/xiaomi/sheng/tools'))
    from package_sheng_recovery_modules import replace_records
    from audit_kernel618_modules import ElfModule
    out = args.out.resolve()
    assert not out.exists()
    parent_pair = json.loads(args.installed_pair.read_text())
    assert parent_pair['passed'] and parent_pair['paired_module_payloads_equal']
    parents = {name: Path(row['path']) for name, row in parent_pair['images'].items()}
    assert set(parents) == {'vendor_boot', 'recovery'}
    assert all(sha(path) == parent_pair['images'][name]['sha256'] for name, path in parents.items())
    module = args.module
    qualification_path = args.module_qualification
    qualification = json.loads(qualification_path.read_text())
    assert qualification['passed']
    expected = next(x for x in qualification['modules'] if x['name'] == 'msm_drm')
    assert sha(module) == expected['signed_sha256']
    newelf = ElfModule(module)
    assert sha(args.current_boot) == args.current_boot_sha256
    out.mkdir(parents=True)
    (out/'images').mkdir()
    (out/'logs').mkdir()
    work = Path(tempfile.mkdtemp(prefix='sheng-dp-current-pair-'))
    unpack = a/'system/tools/mkbootimg/unpack_bootimg.py'
    mkboot = a/'system/tools/mkbootimg/mkbootimg.py'
    avbpath = a/'external/avb/avbtool.py'
    spec = importlib.util.spec_from_file_location('avbtool', avbpath)
    avbtool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(avbtool)

    def run(cmd, label, data=None):
        p = subprocess.run(list(map(str, cmd)), input=data, capture_output=True, timeout=120)
        (out/'logs'/ (label+'.stdout')).write_bytes(p.stdout)
        (out/'logs'/ (label+'.stderr')).write_bytes(p.stderr)
        assert p.returncode == 0, label + ': ' + p.stderr.decode(errors='replace')
        return p.stdout

    def avb_info(image):
        handler = avbtool.ImageHandler(str(image), read_only=True)
        try:
            return avbtool.Avb()._parse_image(handler)
        finally:
            handler._image.close()

    def unpack_args(image, label):
        folder = work/label
        raw = run(['python3', unpack, '--boot_img', image, '--out', folder,
                   '--format', 'mkbootimg', '-0'], label)
        assert raw.endswith(b'\0')
        return [x.decode() for x in raw[:-1].split(b'\0')], folder

    _, boot_parts = unpack_args(args.current_boot, 'current-boot')
    kernel = args.diagnostic_root/'out/arch/arm64/boot/Image'
    assert (boot_parts/'kernel').read_bytes() == kernel.read_bytes(), 'Wrong kernel ABI inputs'
    results, inventories = {}, {}
    abi = None
    for name, parent in parents.items():
        run(['python3', avbpath, 'verify_image', '--image', parent], name+'-parent-footer')
        oldargs, parts = unpack_args(parent, name+'-before')
        if name == 'recovery':
            recovery_kernel = (parts/'kernel').read_bytes()
            # sheng's standalone Recovery header has kernel_size=0 and uses boot_b.
            if recovery_kernel:
                assert recovery_kernel == kernel.read_bytes(), 'Recovery kernel mismatch'
        flag = '--vendor_ramdisk_fragment' if name == 'vendor_boot' else '--ramdisk'
        assert oldargs.count(flag) == 1
        index = oldargs.index(flag)+1
        plain = run(['lz4', '-dc', oldargs[index]], name+'-cpio-before')
        entries, _ = parse_cpio(plain)
        inv = {e['name']: e for e in entries}
        module_path = 'lib/modules/msm_drm.ko'
        oldfile = work/(name+'-old-drm.ko')
        oldfile.write_bytes(inv[module_path]['payload'])
        oldelf = ElfModule(oldfile)
        assert oldelf.info['vermagic'] == newelf.info['vermagic']
        assert oldelf.layout_size == newelf.layout_size and newelf.layout_size > 0
        assert 'module_layout' in newelf.versions()
        if abi is None:
            # Verify against the current 343 module providers, not a stale build directory.
            providers = {}
            for line in (args.diagnostic_root/'out/Module.symvers').read_text().splitlines():
                row = line.split()
                if len(row) >= 3 and row[2] == 'vmlinux':
                    providers.setdefault(row[1], []).append(('vmlinux', int(row[0], 16)))
            count = 0
            for path, record in inv.items():
                if not path.endswith('.ko'):
                    continue
                count += 1
                local = work/('provider-' + Path(path).name)
                local.write_bytes(module.read_bytes() if path == module_path else record['payload'])
                for symbol, crc in ElfModule(local).exports().items():
                    providers.setdefault(symbol, []).append((path, crc))
            assert count == 343
            imports = newelf.versions()
            unversioned = check_imports(newelf, providers)
            btf = args.diagnostic_root/'out/kernel-module-base.btf'
            verifier = args.diagnostic_root/'vendor-kmi32/qualified/host/btf-verify'
            btf_result = run([verifier, 'verify', btf, module], 'btf')
            abi = dict(versioned_imports_checked=len(imports), current_module_providers=count,
                       unversioned_imports=unversioned, btf=json.loads(btf_result),
                       kernel_symvers_sha256=sha(args.diagnostic_root/'out/Module.symvers'),
                       kernel_btf_sha256=sha(btf), module_layout_bytes=newelf.layout_size)

        assert oldelf.exports() == newelf.exports()
        replacements = {module_path: module.read_bytes()}
        packed = replace_records(plain, replacements, parse_cpio)
        compressed = work/(name+'.lz4')
        compressed.write_bytes(run(['lz4', '-l', '-9', '-c'], name+'-compress', packed))
        newargs = oldargs.copy()
        newargs[index] = str(compressed)
        image = out/'images'/(name+'.img')
        run(['python3', mkboot, *newargs, '--vendor_boot' if name == 'vendor_boot' else '--output', image], name+'-pack')
        _, header, desc, _ = avb_info(parent)
        assert header.algorithm_type == 0
        hd = [d for d in desc if isinstance(d, avbtool.AvbHashDescriptor)]
        assert len(hd) == 1 and hd[0].partition_name == name
        hd = hd[0]
        assert hd.flags == 0, "Unsupported non-default hash descriptor flags"
        command = ['python3', avbpath, 'add_hash_footer', '--image', image,
            '--partition_size', parent.stat().st_size, '--partition_name', name,
            '--algorithm', 'NONE', '--salt', hd.salt.hex(), '--hash_algorithm', hd.hash_algorithm,
            '--flags', header.flags, '--rollback_index', header.rollback_index,
            '--rollback_index_location', header.rollback_index_location]
        for d in desc:
            if isinstance(d, avbtool.AvbPropertyDescriptor):
                command += ['--prop', d.key+':'+d.value.decode()]
            else:
                assert isinstance(d, avbtool.AvbHashDescriptor)
        run(command, name+'-seal')
        run(['python3', avbpath, 'verify_image', '--image', image], name+'-footer')
        finalargs, finalparts = unpack_args(image, name+'-after')
        normalize = lambda argv, folder: ['PART/'+Path(x).name if x.startswith(str(folder)+'/') else x for x in argv]
        assert normalize(oldargs, parts) == normalize(finalargs, finalparts)
        for part in ('dtb', 'bootconfig', 'kernel'):
            if (parts/part).exists():
                assert (parts/part).read_bytes() == (finalparts/part).read_bytes()
        assert run(['lz4', '-dc', finalargs[index]], name+'-cpio-after') == packed
        finalentries, _ = parse_cpio(packed)
        finalinv = {e['name']: e for e in finalentries}
        assert set(finalinv) == set(inv)
        assert {p for p in inv if inv[p]['raw'] != finalinv[p]['raw']} == {module_path}
        for path in inv:
            if path not in replacements:
                assert inv[path]['raw'] == finalinv[path]['raw'], path
        _, newheader, newdesc, _ = avb_info(image)
        assert vars(header) == vars(newheader), 'AVB policy/header changed'
        assert [d.encode() for d in desc if not isinstance(d, avbtool.AvbHashDescriptor)] == [
            d.encode() for d in newdesc if not isinstance(d, avbtool.AvbHashDescriptor)]
        inventories[name] = {p: digest(e['payload']) for p,e in finalinv.items() if p.endswith('.ko')}
        results[name] = dict(path=str(image), sha256=sha(image), bytes=image.stat().st_size,
            replaced_paths=sorted(replacements), added_paths=[],
            unchanged_existing_entries=len(inv)-len(replacements), existing_entries=len(inv))
    assert inventories['vendor_boot'] == inventories['recovery']
    assert len(inventories['recovery']) == 343
    receipt = dict(passed=True, offline_only=True, flashed=False, cold_runtime_verified=False,
        parents={k:dict(path=str(v),sha256=sha(v)) for k,v in parents.items()}, images=results,
        paired_module_count=343, paired_module_payloads_equal=True,
        drm_module_sha256=sha(module), drm_loaded_note_sha256=digest(newelf.get('.note.gnu.build-id')),
        abi=abi, parent_pair_sha256=sha(args.installed_pair),
        current_boot_sha256=sha(args.current_boot), kernel_payload_sha256=sha(kernel),
        recovery_has_embedded_kernel=bool(recovery_kernel),
        module_qualification_sha256=sha(qualification_path),
        dp_physical_link_verified=False, runtime_verified=False,
        required_vendor_copy='/vendor/lib/modules/msm_drm.ko',
        unchanged_records_verified=True, header_args_preserved=True, avb_policy_preserved=True,
        standalone_footers_verified=True, full_live_avb_chain_verified=False,
        boot_init_boot_system_vbmeta_unchanged=True, linux_scratch=str(work))
    (out/'qualification.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))


if __name__ == '__main__':
    main()
