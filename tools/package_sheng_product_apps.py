#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Move the declared added applications to product while preserving installed APK bytes."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import sys

from audit_sheng_product_apps import audit
from package_sheng_batch_helpers import certificates, merge_parent, publish_batch, sha, stage_ext4
from package_sheng_location_followup import debugfs
from package_sheng_model_followup import HOST, ROM, run
from package_sheng_overlay_followup import ext4_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installed-package', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[4]
    device = workspace/'device/xiaomi/sheng'
    qualification = audit(device)
    catalog = json.loads((device/'configs/product-apps.json').read_text())
    baseline_reference = args.installed_package.absolute().relative_to(workspace).as_posix()
    baseline_path = args.installed_package.resolve()
    baseline_hash = sha(baseline_path)
    baseline = json.loads(baseline_path.read_text())
    assert baseline['revision'] == 66 and baseline['baseline_revision'] == 65
    assert baseline['complete_avb_chain_verified'] and baseline['native_service_unchanged']
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    assert work.stat().st_dev == Path('/').stat().st_dev and shutil.disk_usage(work).free > 12*1024**3
    run(['python3', device/'tools/prepare_sheng_stylus_swap.py', '--work', work], capture_output=True)
    rows = baseline['files']+baseline['unchanged_partition_files']
    assert len(rows) == 14 and len({r['partition'] for r in rows}) == 14
    chain = {r['partition']: Path(baseline['work_dir'])/'complete-chain'/r['name'] for r in rows}
    for row in rows:
        image = chain[row['partition']]
        assert image.stat().st_size == row['bytes'] and sha(image) == row['sha256'], image
    product = work/'apk-output'
    sources = work/'original-files'
    sources.mkdir()
    entries, removals, nodes, signers = {}, {}, {}, {}
    old = ext4_snapshot(chain['system_ext'])

    def stat_image(image, relative):
        result = run(['debugfs', '-R', 'stat /'+relative, image], capture_output=True, text=True)
        if 'File not found' in result.stderr: return None
        assert 'Inode:' in result.stdout, result.stdout+result.stderr
        return result.stdout

    def add_parents(relative):
        for parent in PurePosixPath(relative).parents:
            if str(parent) == '.': continue
            name = str(parent)
            if name not in nodes and stat_image(chain['product'], name) is None:
                nodes[name] = dict(uid=0, gid=0, mode=0o755, mtime_ns=1230768000*10**9,
                                   selinux='u:object_r:system_file:s0')

    for row in catalog['applications']+catalog['companions']:
        relative = row['path']
        assert stat_image(chain['product'], relative) is None, 'Destination already exists: '+relative
        original = sources/relative
        original.parent.mkdir(parents=True, exist_ok=True)
        mtime = 1230768000
        if row.get('new_source'):
            metadata = json.loads((device/'interfaces/input/ime/source.json').read_text())
            apk = device/row['new_source']
            assert sha(apk) == metadata['sha256'] and apk.stat().st_size == metadata['bytes']
            shutil.copyfile(apk, original)
            jdk = ROM/'prebuilts/jdk/jdk21/linux-x86/bin'
            signature = run([jdk/'java', '-Xmx256m', '-jar', ROM/'prebuilts/sdk/tools/linux/lib/apksigner.jar',
                             'verify', '--verbose', '--print-certs', original], capture_output=True, text=True)
            assert 'certificate SHA-256 digest: '+metadata['certificate_sha256'] in signature.stdout
            (work/'ime-signature.log').write_text(signature.stdout+signature.stderr)
            run(['python3', ROM/'build/soong/scripts/check_prebuilt_presigned_apk.py', '--preprocessed',
                 '--aapt2', HOST/'aapt2', '--zipalign', HOST/'zipalign', original, work/'ime-preprocessed.stamp'],
                capture_output=True)
        else:
            info = stat_image(chain['system_ext'], relative)
            assert info is not None, relative
            inode = old['inodes'][int(re.search(r'Inode:\s*(\d+)', info)[1])]
            assert struct.unpack_from('<H', inode, 0)[0] & 0o177777 == 0o100644
            assert all(struct.unpack_from('<H', inode, offset)[0] == 0 for offset in (2, 24, 120, 122))
            assert struct.unpack_from('<H', inode, 26)[0] == 1
            mtime = struct.unpack_from('<I', inode, 16)[0]
            debugfs(chain['system_ext'], f'dump /{relative} {original}')
            removals[relative] = sha(original)
        target = product/'product'/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        entries[relative] = dict(source=str(target), bytes=target.stat().st_size, sha256=sha(target))
        nodes[relative] = dict(uid=0, gid=0, mode=0o644, mtime_ns=mtime*10**9,
                               selinux='u:object_r:system_file:s0')
        add_parents(relative)
        if relative.endswith('.apk'): signers[relative] = original
    capacity = run(['dumpe2fs', '-h', chain['product']], capture_output=True, text=True)
    (work/'product-capacity.log').write_text(capacity.stdout+capacity.stderr)
    free = int(re.search(r'^Free blocks:\s*(\d+)', capacity.stdout, re.M)[1])
    block_size = int(re.search(r'^Block size:\s*(\d+)', capacity.stdout, re.M)[1])
    assert free*block_size > sum(r['bytes'] for r in entries.values())+32*1024**2
    print('Moving the declared APKs and companion files; original signatures and partition sizes are retained.', flush=True)
    sys.path.insert(0, str(ROM/'external/avb'))
    import avbtool
    avb = avbtool.Avb()
    platform = certificates(sources/'priv-app/ShengStylus/ShengStylus.apk')
    product_image, product_descriptor, product_stage = stage_ext4('product', chain['product'], entries, nodes,
        work, avb, avbtool, platform, source_product=product, new_apk_certificates=signers)
    print('Product contents verified; removing the matching old system_ext copies.', flush=True)
    ext_image, ext_descriptor, ext_stage = stage_ext4('system_ext', chain['system_ext'], {}, {},
        work, avb, avbtool, platform, removals=removals)
    outputs = {'product': product_image, 'system_ext': ext_image, 'vbmeta_system': work/'vbmeta_system.img'}
    merge_parent(avb, avbtool, chain['vbmeta_system'], [product_descriptor, ext_descriptor],
                 outputs['vbmeta_system'], 'SHA256_RSA2048', work)
    complete = work/'complete-chain'
    complete.mkdir()
    for name, path in chain.items(): (complete/(name+'.img')).symlink_to(outputs.get(name, path).resolve())
    verified = run([HOST/'avbtool', 'verify_image', '--image', complete/'vbmeta.img', '--follow_chain_partitions'],
                   capture_output=True, text=True)
    (work/'avb-verification.log').write_text(verified.stdout+verified.stderr)
    assert audit(device) == qualification and sha(baseline_path) == baseline_hash
    report = dict(kind='product-app-layout', date_utc=datetime.now(timezone.utc).isoformat(),
        baseline_manifest=baseline_reference, baseline_manifest_sha256=baseline_hash,
        baseline_partitions=rows, unchanged_partition_files=[r for r in rows if r['partition'] not in outputs],
        entries={'product': entries}, removals={'system_ext': removals},
        partition_reports={'product': product_stage, 'system_ext': ext_stage},
        applications=catalog['applications'], source_sha256=qualification['source_sha256'],
        work_dir=str(work), complete_avb_chain_verified=True, partition_sizes_unchanged=True,
        policy_and_vintf_inputs_unchanged=True, installed_application_bytes_preserved=True,
        preinstalled_ime_included=True, native_service_unchanged=True, systemui_unchanged=True,
        normal_module_build_passed=False, full_product_build_passed=False, ninja_graph_loaded=False,
        installed=False, e_drive_swap_allowed=False, native_c_staging=True)
    destination = args.output.resolve()
    publish_batch(destination, outputs, report)
    print(destination/'build-result.json', flush=True)


if __name__ == '__main__':
    main()
