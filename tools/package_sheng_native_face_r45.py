#!/usr/bin/env python3
"""Seal the native runtime/session fixes over the verified r44 partition chain."""
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

PATHS = ['priv-app/ShengFaceUnlock/ShengFaceUnlock.apk', 'framework/ShengNativeFaceBootstrap.jar']

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--build-review',type=Path,required=True)
    parser.add_argument('--post-audit',type=Path,required=True)
    args=parser.parse_args();assert __debug__
    workspace=args.workspace.resolve(strict=True)
    review=json.loads(args.build_review.read_text());audit=json.loads(args.post_audit.read_text())
    assert review['revision']==45 and review['normal_module_build_passed']
    assert review['native_manifest_without_app_components'] and review['native_and_model_payload_verified']
    assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
    assert datetime.now(timezone.utc).timestamp()-datetime.fromisoformat(audit['date_utc']).timestamp()<7200
    for relative,digest in review['sources_sha256'].items():assert sha(workspace/relative)==sha(ROM/relative)==digest,relative
    parent_dir=workspace/'artifacts/system-hardware-followup-sheng-r44'
    parent=json.loads((parent_dir/'build-result.json').read_text())
    assert parent['revision']==44 and parent['complete_avb_chain_verified'] and parent['original_systemui_unchanged']
    assert parent['boot_policy']['actual_partition_combination_compiled'] and parent['vintf']['actual_partition_combination_compatible']
    chain={};digests={}
    restored=json.loads((workspace/'reports/device/r38-restore-20261110/restore-manifest.json').read_text())
    assert restored['complete_avb_chain_verified']
    for entry in restored['files']:
        path=workspace/entry['path'];assert path.stat().st_size==entry['bytes'] and sha(path)==entry['sha256']
        chain[entry['partition']]=path;digests[entry['partition']]=entry['sha256']
    for revision in [39,40,41,42,44]:
        directory=workspace/f'artifacts/system-hardware-followup-sheng-r{revision}'
        manifest=json.loads((directory/'build-result.json').read_text())
        assert manifest['revision']==revision and manifest['complete_avb_chain_verified']
        assert manifest['all_filesystem_stages_verified'] and manifest['original_systemui_unchanged']
        for entry in manifest['files']:
            path=directory/entry['name'];assert path.stat().st_size==entry['bytes'] and sha(path)==entry['sha256']
            chain[entry['partition']]=path;digests[entry['partition']]=entry['sha256']
    entries={'system_ext':{path:review['entries']['system_ext'][path] for path in PATHS}}
    validate_inputs('system_ext',entries['system_ext'])
    destination=workspace/'artifacts/system-hardware-followup-sheng-r45';assert not destination.exists()
    work=Path(tempfile.mkdtemp(prefix='r45-native-face-package-',dir='/root/sheng-lineage/hardware-diagnostics'))
    assert shutil.disk_usage(work).free>15*1024**3
    sys.path.insert(0,str(ROM/'external/avb'));import avbtool
    avb=avbtool.Avb();reference=work/'original-SystemUI.apk'
    debugfs(chain['system_ext'],f'dump /priv-app/SystemUI/SystemUI.apk {reference}')
    assert sha(reference)=='33017b0d59e28da5db3e089a98f49601de508228a012392ee2d04c82cda3ccb1'
    print('Staging only native APK and bootstrap over r44',flush=True)
    image,tree,report=stage_ext4('system_ext',chain['system_ext'],entries['system_ext'],{},work,avb,avbtool,certificates(reference))
    assert set(report['changed_files'])==set(PATHS) and report['metadata_preserved']
    outputs={'system_ext':image,'vbmeta_system':work/'vbmeta_system.img'}
    merge_parent(avb,avbtool,chain['vbmeta_system'],[tree],outputs['vbmeta_system'],'SHA256_RSA2048',work)
    complete=work/'complete-chain';complete.mkdir()
    cached={}
    # Copy and hash unchanged inputs sequentially. The standard AVB verifier then
    # reads its 4 KiB blocks on the local filesystem instead of through drvfs.
    # Every cached byte must match the already verified parent manifest digest.
    for part,path in chain.items():
        if part in outputs:target=outputs[part]
        else:
            target=work/f'base-{part}.img';shutil.copyfile(path,target)
            assert sha(target)==digests[part];cached[part]=digests[part]
        (complete/(part+'.img')).symlink_to(target.resolve())
    print('Verifying the complete AVB chain using byte-verified local inputs',flush=True)
    result=subprocess.run([HOST/'avbtool','verify_image','--image',complete/'vbmeta.img','--follow_chain_partitions'],text=True,capture_output=True)
    (work/'complete-chain.avb.txt').write_text(result.stdout+result.stderr)
    assert result.returncode==0,result.stdout+result.stderr
    for relative,digest in review['sources_sha256'].items():assert sha(workspace/relative)==sha(ROM/relative)==digest,relative
    validate_inputs('system_ext',entries['system_ext'])
    for part,path in chain.items():assert sha(path)==digests[part]
    evidence=workspace/'reports/device/20261110-resume/face-native/r45-package';evidence.mkdir(exist_ok=False)
    for path in work.iterdir():
        if path.is_file() and path.suffix in ['.log','.txt','.json']:shutil.copyfile(path,evidence/path.name)
    publish_batch(destination,outputs,dict(revision=45,baseline_sha256={part:digests[part] for part in outputs},
        build_review_sha256=sha(args.build_review),post_audit_sha256=sha(args.post_audit),
        source_commit=subprocess.check_output(['git','-C',workspace,'rev-parse','HEAD'],text=True).strip(),
        sources_sha256=review['sources_sha256'],entries=entries,partition_reports={'system_ext':report},
        boot_policy=parent['boot_policy'],vintf=parent['vintf'],cached_avb_inputs_sha256=cached,
        policy_and_vintf_unchanged_from_verified_r44=True,all_filesystem_stages_verified=True,
        complete_avb_chain_verified=True,original_systemui_unchanged=True,normal_module_build_passed=True,
        native_manifest_without_app_components=True,full_product_build_passed=False,
        hardware_boot_tested=False,native_settings_enrollment_tested=False,keyguard_authentication_tested=False,
        persistent_build_evidence_dir=str(evidence),work_dir=str(work)))
    print(destination,flush=True)

if __name__=='__main__':main()
