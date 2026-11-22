#!/usr/bin/env python3
"""Bind final pystore qualification to this build's signed Android module stage.

Offline inputs only: no image, AVB-chain, SELinux or runtime acceptance.
"""
import argparse
import json
from pathlib import Path
from sheng_kernel_image import qualify, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    build = args.build.resolve(strict=True)
    core = build / 'core'
    stage = build / 'SHENG_VENDOR_KERNEL_OBJ/android-modules'
    verification = build / 'SHENG_VENDOR_KERNEL_OBJ/qualified/verification.json'
    linked = build / 'pystore-final-kernel-qualification.json'
    prepared = stage / 'prepared.json'
    q, k, p = [json.loads(path.read_text()) for path in (verification, linked, prepared)]
    if args.out.exists():
        raise ValueError('Preserve previous receipt; choose a new output')
    assert q['passed'] and q['phase'] == 'complete'
    assert all(q[name] is True for name in
               ('abi_passed', 'btf_passed', 'dependency_graph_passed', 'namespaces_passed'))
    assert k['passed'] and k['current_source_compile_replayed_byte_identical']
    assert k['logger_identity_verified_in_object_and_vmlinux']
    assert k['pystore_boot_only_verified_in_object_and_vmlinux']
    assert Path(p['qualification']).resolve() == verification
    assert Path(p['final_kernel_out']).resolve() == core
    clang = Path('/root/sheng-pixelos/diagnostics/kernel618-android-deps/prebuilts/clang/host/linux-x86/clang-r584948c/bin')
    final = qualify(core, clang / 'llvm-objcopy')
    assert final == k['final_kernel_image'] == p['final_kernel_image']
    assert final['kernel_image_sha256'] == q['image_sha256'] == p['kernel_image_sha256']
    for name, digest in k['artifacts_sha256'].items():
        assert sha(core / name) == digest, name
    assert p['module_count'] == len(p['modules']) == 474
    assert not p['deferred_legacy_names']
    filenames = set()
    for row in p['modules'].values():
        filename = row['filename']
        assert Path(filename).name == filename and filename.endswith('.ko')
        assert filename not in filenames
        filenames.add(filename)
        assert all(row[key] is True for key in ('btf_unchanged', 'imports_crc_unchanged',
                                               'exports_crc_unchanged', 'signature_verified'))
        path = stage / 'modules' / filename
        assert not path.is_symlink() and path.stat().st_size == row['packaged_bytes']
        assert sha(path) == row['packaged_sha256'], filename
    counts = {}
    for name in ('vendor_ramdisk', 'vendor_dlkm', 'system_dlkm'):
        files = list((stage / name).rglob('*.ko'))
        for path in files:
            assert path.name in filenames and not path.is_symlink()
            assert sha(path) == sha(stage / 'modules' / path.name), str(path)
        counts[name] = len(files)
    assert counts == dict(vendor_ramdisk=343, vendor_dlkm=472, system_dlkm=2), counts
    result = dict(passed=True, scope='offline final pystore core and staged modules only',
                  diagnostic_only=False, bootlog_disabled=False,
                  logger_identity_verified_in_object_and_vmlinux=True,
                  pystore_boot_only_verified_in_object_and_vmlinux=True,
                  prepared_sha256=sha(prepared), verification_sha256=sha(verification),
                  linked_kernel_qualification_sha256=sha(linked),
                  core={'arch/arm64/boot/Image': final['kernel_image_sha256']},
                  final_kernel_image=final, layer_counts=counts,
                  full_provider_count=q['module_count'], signed_unique_module_count=p['module_count'],
                  packaged_images=False, full_avb_chain_verified=False,
                  policy_system_integration_verified=False, runtime_verified=False,
                  rawdump_preservation_runtime_verified=False, flashed=False)
    with args.out.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
