#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Preinstall the original handwriting APK in product over an exact sealed pen update."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sys

from package_sheng_batch_helpers import certificates, merge_parent, publish_batch, sha, stage_ext4
from package_sheng_model_followup import HOST, ROM, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installed-package', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[4]
    device = workspace/'device/xiaomi/sheng'
    source = device/'interfaces/input/ime'
    baseline_reference = args.installed_package.absolute().relative_to(workspace).as_posix()
    baseline_path = args.installed_package.resolve()
    baseline = json.loads(baseline_path.read_text())
    assert baseline['revision'] == 66 and baseline['baseline_revision'] == 65
    assert baseline['complete_avb_chain_verified'] and baseline['native_service_unchanged']
    assert baseline['targeted_ui_build_passed'] and not baseline.get('preinstalled_ime_included', False)
    baseline_hash = sha(baseline_path)
    snapshot = lambda: {p.relative_to(device).as_posix(): sha(p)
                        for p in sorted(source.rglob('*')) if p.is_file()} | {'device.mk': sha(device/'device.mk')}
    sources = snapshot()
    bp = (source/'Android.bp').read_text()
    assert re.search(r'\bproduct_specific\s*:\s*true\s*,', bp)
    assert 'system_ext_specific' not in bp
    assert re.search(r'\bpresigned\s*:\s*true\s*,', bp)
    assert re.search(r'\bpreprocessed\s*:\s*true\s*,', bp)
    assert re.search(r'\bShengSogouIme\b', (device/'device.mk').read_text())
    metadata = json.loads((source/'source.json').read_text())
    original = source/'proprietary/SogouIme.apk'
    assert metadata['package'] == 'com.sohu.inputmethod.sogouoem'
    assert original.stat().st_size == metadata['bytes'] and sha(original) == metadata['sha256']
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    assert work.stat().st_dev == Path('/').stat().st_dev
    assert shutil.disk_usage(work).free > 12*1024**3
    run(['python3', device/'tools/prepare_sheng_stylus_swap.py', '--work', work], capture_output=True)
    rows = baseline['files'] + baseline['unchanged_partition_files']
    assert len(rows) == 14 and len({r['partition'] for r in rows}) == 14
    chain = {r['partition']: Path(baseline['work_dir'])/'complete-chain'/r['name'] for r in rows}
    for row in rows:
        path = chain[row['partition']]
        assert path.stat().st_size == row['bytes'] and sha(path) == row['sha256'], path
    capacity = run(['dumpe2fs', '-h', chain['product']], capture_output=True, text=True)
    (work/'product-capacity.log').write_text(capacity.stdout+capacity.stderr)
    block_size = int(re.search(r'^Block size:\s*(\d+)', capacity.stdout, re.M)[1])
    free_blocks = int(re.search(r'^Free blocks:\s*(\d+)', capacity.stdout, re.M)[1])
    assert free_blocks*block_size >= metadata['bytes']+32*1024**2
    print('Product has sufficient free blocks; qualifying the original APK and preserving partition sizes.', flush=True)
    jdk = ROM/'prebuilts/jdk/jdk21/linux-x86/bin'
    signature = run([jdk/'java', '-Xmx256m', '-jar', ROM/'prebuilts/sdk/tools/linux/lib/apksigner.jar',
                     'verify', '--verbose', '--print-certs', original], capture_output=True, text=True)
    (work/'apk-signature.log').write_text(signature.stdout+signature.stderr)
    assert 'certificate SHA-256 digest: '+metadata['certificate_sha256'] in signature.stdout
    check = run(['python3', ROM/'build/soong/scripts/check_prebuilt_presigned_apk.py', '--preprocessed',
                 '--aapt2', HOST/'aapt2', '--zipalign', HOST/'zipalign', original, work/'preprocessed.stamp'],
                capture_output=True, text=True)
    (work/'preprocessed-check.log').write_text(check.stdout+check.stderr)
    product = work/'apk-output'
    relative = 'app/ShengSogouIme/ShengSogouIme.apk'
    apk = product/'product'/relative
    apk.parent.mkdir(parents=True)
    shutil.copyfile(original, apk)
    entries = {relative: dict(source=str(apk), bytes=metadata['bytes'], sha256=metadata['sha256'])}
    nodes = {name: dict(uid=0, gid=0, mode=mode, mtime_ns=1230768000*10**9,
                       selinux='u:object_r:system_file:s0')
             for name, mode in [('app/ShengSogouIme', 0o755), (relative, 0o644)]}
    sys.path.insert(0, str(ROM/'external/avb'))
    import avbtool
    avb = avbtool.Avb()
    image, descriptor, stage = stage_ext4('product', chain['product'], entries, nodes, work, avb, avbtool,
        certificates(original), source_product=product, new_apk_certificates={relative: original})
    assert stage['metadata_preserved']
    outputs = {'product': image, 'vbmeta_system': work/'vbmeta_system.img'}
    merge_parent(avb, avbtool, chain['vbmeta_system'], [descriptor], outputs['vbmeta_system'], 'SHA256_RSA2048', work)
    complete = work/'complete-chain'
    complete.mkdir()
    for name, path in chain.items():
        (complete/(name+'.img')).symlink_to(outputs.get(name, path).resolve())
    verification = run([HOST/'avbtool', 'verify_image', '--image', complete/'vbmeta.img', '--follow_chain_partitions'],
                       capture_output=True, text=True)
    (work/'avb-verification.log').write_text(verification.stdout+verification.stderr)
    assert sha(baseline_path) == baseline_hash and snapshot() == sources
    report = dict(kind='targeted-handwriting-ime-preinstall', revision=66, baseline_revision=66,
        date_utc=datetime.now(timezone.utc).isoformat(),
        baseline_manifest=baseline_reference, baseline_manifest_sha256=baseline_hash,
        baseline_partitions=rows, unchanged_partition_files=[r for r in rows if r['partition'] not in outputs],
        entries={'product': entries}, partition_reports={'product': stage}, work_dir=str(work),
        source_sha256=sources, complete_avb_chain_verified=True, partition_sizes_unchanged=True,
        policy_and_vintf_inputs_unchanged=True, native_service_unchanged=True, systemui_unchanged=True,
        preinstalled_ime_included=True, prebuilt_ime_qualified=True, ime_original_signature_preserved=True,
        ime_certificate_sha256=metadata['certificate_sha256'], product_registration_sha256=sources['device.mk'],
        normal_module_build_passed=False, full_product_build_passed=False, ninja_graph_loaded=False,
        installed=False, e_drive_swap_allowed=False, native_c_staging=True)
    destination = args.output.resolve()
    publish_batch(destination, outputs, report)
    print(destination/'build-result.json', flush=True)


if __name__ == '__main__':
    main()
