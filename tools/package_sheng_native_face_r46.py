#!/usr/bin/env python3
"""Seal native Face key namespace and diagnostics over the verified r45 chain."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from package_sheng_batch_helpers import certificates, debugfs, merge_parent, publish_batch, stage_ext4, validate_inputs
from package_sheng_model_followup import HOST, ROM, sha
from package_sheng_native_face_r44 import verify_boot_policy

PATHS = ['priv-app/ShengFaceUnlock/ShengFaceUnlock.apk',
         'bin/sheng-face',
         'etc/selinux/system_ext_sepolicy.cil',
         'etc/selinux/system_ext_sepolicy_and_mapping.sha256',
         'etc/selinux/system_ext_keystore2_key_contexts']

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--build-review', type=Path, required=True)
    parser.add_argument('--post-audit', type=Path, required=True)
    args = parser.parse_args(); assert __debug__
    workspace = args.workspace.resolve(strict=True)
    review = json.loads(args.build_review.read_text()); audit = json.loads(args.post_audit.read_text())
    assert review['revision'] == 46 and review['normal_module_build_passed']
    assert review['native_manifest_without_app_components'] and review['native_and_model_payload_verified']
    assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
    assert datetime.now(timezone.utc).timestamp()-datetime.fromisoformat(audit['date_utc']).timestamp() < 7200
    for p, digest in review['sources_sha256'].items(): assert sha(workspace/p) == sha(ROM/p) == digest, p
    chain, digests = {}, {}
    restored = json.loads((workspace/'reports/device/r38-restore-20261110/restore-manifest.json').read_text())
    assert restored['complete_avb_chain_verified']
    for entry in restored['files']:
        path = workspace/entry['path']; assert path.stat().st_size == entry['bytes'] and sha(path) == entry['sha256']
        chain[entry['partition']] = path; digests[entry['partition']] = entry['sha256']
    manifests = {}
    for revision in [39,40,41,42,44,45]:
        directory = workspace/f'artifacts/system-hardware-followup-sheng-r{revision}'
        parent = json.loads((directory/'build-result.json').read_text()); manifests[revision] = parent
        assert parent['revision'] == revision and parent['complete_avb_chain_verified']
        assert parent['all_filesystem_stages_verified'] and parent['original_systemui_unchanged']
        for entry in parent['files']:
            path = directory/entry['name']; assert path.stat().st_size == entry['bytes'] and sha(path) == entry['sha256']
            chain[entry['partition']] = path; digests[entry['partition']] = entry['sha256']
    parent = manifests[44]
    assert parent['boot_policy']['actual_partition_combination_compiled'] and parent['vintf']['actual_partition_combination_compatible']
    entries = {'system_ext': {p: review['entries']['system_ext'][p] for p in PATHS}}
    validate_inputs('system_ext', entries['system_ext'])
    destination = workspace/'artifacts/system-hardware-followup-sheng-r46'; assert not destination.exists()
    work = Path(tempfile.mkdtemp(prefix='r46-native-face-package-', dir='/root/sheng-lineage/hardware-diagnostics'))
    assert shutil.disk_usage(work).free > 15*1024**3
    sys.path.insert(0, str(ROM/'external/avb')); import avbtool
    avb = avbtool.Avb(); reference = work/'original-SystemUI.apk'
    debugfs(chain['system_ext'], f'dump /priv-app/SystemUI/SystemUI.apk {reference}')
    assert sha(reference) == '33017b0d59e28da5db3e089a98f49601de508228a012392ee2d04c82cda3ccb1'
    # Only APK mtime changes deliberately, to invalidate the platform parse cache.
    nodes = {}  # r45 already has the generated, empty key-contexts file.
    print('Staging r46 APK and dedicated key policy over r45', flush=True)
    image, tree, report = stage_ext4('system_ext', chain['system_ext'], entries['system_ext'], nodes,
        work, avb, avbtool, certificates(reference),
        replacement_mtimes={'priv-app/ShengFaceUnlock/ShengFaceUnlock.apk':1230768046})
    assert set(report['changed_files']) == set(PATHS) and report['metadata_preserved']
    before, after = work/'system_ext-before', work/'system_ext-after'
    for p in (before/'etc/selinux').rglob('*'):
        if p.is_file() and str(p.relative_to(before)) not in PATHS:
            assert p.read_bytes() == (after/p.relative_to(before)).read_bytes(), p
    # Vendor/ODM policy is unchanged since r44. Verify extracted baseline policy
    # bytes against the r44 receipt before copying them for the new split compile.
    old_work = Path(parent['work_dir']).resolve(strict=True)
    for relative, digest in parent['boot_policy']['input_sha256'].items():
        if relative.startswith(('vendor-tree/', 'odm-tree/')): assert sha(old_work/relative) == digest
    for part in ['vendor','odm']:
        source = old_work/f'{part}-tree/etc/selinux'
        target = work/f'{part}-tree/etc/selinux'; target.parent.mkdir(parents=True)
        shutil.copytree(source,target)
    boot_policy = verify_boot_policy(chain,work)
    assert (after/'etc/selinux/system_ext_sepolicy_and_mapping.sha256').read_bytes() != \
        (work/'odm-tree/etc/selinux/precompiled_sepolicy.system_ext_sepolicy_and_mapping.sha256').read_bytes()
    contexts = (after/'etc/selinux/system_ext_keystore2_key_contexts').read_text()
    assert [p.split() for p in contexts.splitlines() if p.strip() and not p.lstrip().startswith('#')] == [['10001','u:object_r:sheng_face_key:s0']]
    # Metadata/overlays/feature declaration remain byte-identical to verified r44.
    for part in ['odm','vendor']:
        for p,entry in review['entries'][part].items(): assert entry['sha256'] == parent['entries'][part][p]['sha256']
    outputs = {'system_ext': image, 'vbmeta_system': work/'vbmeta_system.img'}
    merge_parent(avb,avbtool,chain['vbmeta_system'],[tree],outputs['vbmeta_system'],'SHA256_RSA2048',work)
    complete = work/'complete-chain'; complete.mkdir(); cached = {}
    for part,path in chain.items():
        if part in outputs: target = outputs[part]
        else:
            target = work/f'base-{part}.img'; shutil.copyfile(path,target)
            assert sha(target) == digests[part]; cached[part] = digests[part]
        (complete/(part+'.img')).symlink_to(target.resolve())
    print('Verifying complete AVB chain and actual split policy', flush=True)
    result = subprocess.run([HOST/'avbtool','verify_image','--image',complete/'vbmeta.img','--follow_chain_partitions'],text=True,capture_output=True)
    (work/'complete-chain.avb.txt').write_text(result.stdout+result.stderr); assert result.returncode == 0,result.stdout+result.stderr
    for p,digest in review['sources_sha256'].items(): assert sha(workspace/p) == sha(ROM/p) == digest,p
    validate_inputs('system_ext',entries['system_ext'])
    for part,path in chain.items(): assert sha(path) == digests[part]
    evidence = workspace/'reports/device/20261110-resume/face-native/r46-package'; evidence.mkdir(exist_ok=False)
    for p in work.iterdir():
        if p.is_file() and p.suffix in ['.log','.txt','.json']: shutil.copyfile(p,evidence/p.name)
    publish_batch(destination,outputs,dict(revision=46,baseline_sha256={p:digests[p] for p in outputs},
        build_review_sha256=sha(args.build_review),post_audit_sha256=sha(args.post_audit),
        source_commit=subprocess.check_output(['git','-C',workspace,'rev-parse','HEAD'],text=True).strip(),
        sources_sha256=review['sources_sha256'],entries=entries,partition_reports={'system_ext':report},
        boot_policy=boot_policy,vintf=parent['vintf'],cached_avb_inputs_sha256=cached,
        vintf_unchanged_from_verified_r44=True,all_filesystem_stages_verified=True,
        complete_avb_chain_verified=True,original_systemui_unchanged=True,normal_module_build_passed=True,
        native_manifest_without_app_components=True,full_product_build_passed=False,
        hardware_boot_tested=False,native_settings_enrollment_tested=False,keyguard_authentication_tested=False,
        persistent_build_evidence_dir=str(evidence),work_dir=str(work)))
    print(destination,flush=True)

if __name__ == '__main__': main()
