#!/usr/bin/env python3
"""Seal the native Face service over the byte-verified r42 partition chain."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from package_sheng_batch_helpers import (certificates, debugfs, merge_parent, publish_batch,
    stage_ext4, stage_erofs, validate_inputs, validate_packaging_inputs,
    erofs_input_keys, packaging_input_path)
from package_sheng_model_followup import HOST, PRODUCT, ROM, sha
from review_sheng_native_face import SCOPE

BASELINE = {
    'system_ext': '5e0a82811f901951205f9051c646d787aa430ba7948a60995c24ffe5cffcdc2a',
    'odm': '456d3908dddffee1545172bd2c328531547744a0f74b619379c2ec977339bce3',
    'vendor': '5d0552dbf72d4dc02be55ac60148b34b1086c8589988d799d433c56b436bd767',
    'vbmeta': '5c00e7bd310324d75cc1db34b8e9d1261c4119a11b71b63dd926eace87791fd1',
    'vbmeta_system': '5ca478ff5ad265a065040676f1d634870bf75d077d3b73aa8b298846ebea97ef',
}

def verify_vintf(chain_inputs, work, runtime):
    """Check manifests extracted from the actual candidate partition combination."""
    runtime = runtime.resolve(strict=True)
    baseline = json.loads((runtime/'vintf-review.json').read_text())[0]
    assert baseline['returncode']==0, 'The live baseline must already be compatible'
    roots={}
    for part in ['system','product']:
        root=work/(part+'-vintf');root.mkdir()
        prefix='/system' if part=='system' else ''
        debugfs(chain_inputs[part],f'rdump {prefix}/etc/vintf {root}')
        (root/'etc').mkdir();shutil.move(root/'vintf',root/'etc/vintf');roots[part]=root
    roots.update(system_ext=work/'system_ext-after',vendor=work/'vendor-tree',
                 odm=work/'odm-tree',apex=runtime/'apex')
    assert not (roots['system_ext']/'etc/vintf/manifest/face-native.xml').exists()
    assert (roots['odm']/'etc/vintf/manifest/face-native.xml').is_file()
    command=[HOST/'checkvintf','--check-compat']
    for part,root in roots.items():command+=['--dirmap','/'+part+':'+str(root)]
    command+=['--property','ro.product.first_api_level=34',
              '--property','ro.boot.product.hardware.sku=sheng',
              '--property','ro.boot.product.vendor.sku=kalama',
              '--property','apex.all.ready=true','--kernel','5.15.220:'+str(runtime/'kernel.config')]
    result=subprocess.run(list(map(str,command)),text=True,capture_output=True,
        env={**os.environ,'LD_LIBRARY_PATH':str(HOST.parent/'lib64')})
    (work/'combined-vintf.log').write_text(result.stdout+result.stderr)
    assert result.returncode==0,result.stdout+result.stderr
    return dict(actual_partition_combination_compatible=True,kernel_version='5.15.220',
        kernel_config_sha256=sha(runtime/'kernel.config'),
        apex_inputs_sha256={str(path.relative_to(runtime)):sha(path)
                           for path in (runtime/'apex').rglob('*') if path.is_file()})

def verify_boot_policy(chain_inputs, work):
    """Compile the actual partition combination, using init's split-policy inputs."""
    roots={name:work/(name+'-policy') for name in ['system','product']}
    for name,root in roots.items():
        root.mkdir()
        prefix='/system' if name=='system' else ''
        debugfs(chain_inputs[name],f'rdump {prefix}/etc/selinux {root}')
        roots[name]=root/'selinux'
    roots['system_ext']=work/'system_ext-after/etc/selinux'
    roots['vendor']=work/'vendor-tree/etc/selinux'
    roots['odm']=work/'odm-tree/etc/selinux'
    version=(roots['vendor']/'plat_sepolicy_vers.txt').read_text().strip()
    genfs=(roots['vendor']/'genfs_labels_version.txt').read_text().strip()
    selected=[roots['system']/'plat_sepolicy.cil',roots['system']/f'mapping/{version}.cil']
    for part,relative in [('system',f'mapping/{version}.compat.cil'),
                          ('system_ext','system_ext_sepolicy.cil'),
                          ('system_ext',f'mapping/{version}.cil'),
                          ('system_ext',f'mapping/{version}.compat.cil'),
                          ('product','product_sepolicy.cil'),('product',f'mapping/{version}.cil'),
                          ('vendor','plat_pub_versioned.cil'),('vendor','vendor_sepolicy.cil'),
                          ('odm','odm_sepolicy.cil'),('system',f'plat_sepolicy_genfs_{genfs}.cil')]:
        path=roots[part]/relative
        if path.is_file():selected.append(path)
    assert all(path.is_file() for path in selected)
    command=[HOST/'secilc',selected[0],'-m','-M','true','-G','-N','-c','30',
             selected[1],'-o',work/'combined-boot-policy','-f','/dev/null',*selected[2:]]
    r=subprocess.run(command,text=True,capture_output=True)
    (work/'combined-boot-policy.log').write_text(r.stdout+r.stderr)
    assert r.returncode==0,r.stdout+r.stderr
    return dict(actual_partition_combination_compiled=True,
                vendor_policy_version=version,genfs_labels_version=genfs,
                input_sha256={str(path.relative_to(work)):sha(path) for path in selected})

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--build-review',type=Path,required=True)
    p.add_argument('--post-audit',type=Path,required=True)
    p.add_argument('--runtime-vintf',type=Path,required=True)
    args=p.parse_args();assert __debug__
    workspace=args.workspace.resolve(strict=True)
    review=json.loads(args.build_review.read_text());audit=json.loads(args.post_audit.read_text())
    assert review['revision']==44 and review['normal_module_build_passed']
    assert review['native_manifest_without_app_components'] and review['native_and_model_payload_verified']
    assert review['api1_bootstrap_compile_passed']
    assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
    assert datetime.now(timezone.utc).timestamp()-datetime.fromisoformat(audit['date_utc']).timestamp()<7200
    for rel,digest in review['sources_sha256'].items(): assert sha(workspace/rel)==sha(ROM/rel)==digest,rel
    entries=review['entries'];assert set(entries)==set(SCOPE)
    for part,paths in SCOPE.items(): assert set(entries[part])==set(paths);validate_inputs(part,entries[part])
    frozen={key:sha(packaging_input_path(key)) for key in set().union(*(erofs_input_keys(x) for x in ['odm','vendor']))}
    validate_packaging_inputs(SCOPE,frozen)
    restored=json.loads((workspace/'reports/device/r38-restore-20261110/restore-manifest.json').read_text())
    assert restored['complete_avb_chain_verified']
    chain_inputs={}
    for entry in restored['files']:
        path=workspace/entry['path'];assert path.stat().st_size==entry['bytes'] and sha(path)==entry['sha256']
        chain_inputs[entry['partition']]=path
    for revision in [39,40,41,42]:
        directory=workspace/f'artifacts/system-hardware-followup-sheng-r{revision}'
        parent=json.loads((directory/'build-result.json').read_text())
        assert parent['revision']==revision and parent['complete_avb_chain_verified']
        assert parent['all_filesystem_stages_verified'] and parent['original_systemui_unchanged']
        for entry in parent['files']:
            path=directory/entry['name'];assert path.stat().st_size==entry['bytes'] and sha(path)==entry['sha256']
            chain_inputs[entry['partition']]=path
    assert {part:sha(chain_inputs[part]) for part in BASELINE}==BASELINE
    destination=workspace/'artifacts/system-hardware-followup-sheng-r44';assert not destination.exists()
    work=Path(tempfile.mkdtemp(prefix='r44-native-face-package-',dir='/root/sheng-lineage/hardware-diagnostics'))
    assert shutil.disk_usage(work).free>15*1024**3
    sys.path.insert(0,str(ROM/'external/avb'));import avbtool
    avb=avbtool.Avb()
    reference=work/'original-SystemUI.apk'
    debugfs(chain_inputs['system_ext'],f'dump /priv-app/SystemUI/SystemUI.apk {reference}')
    assert sha(reference)=='33017b0d59e28da5db3e089a98f49601de508228a012392ee2d04c82cda3ccb1'
    runtime=work/'original-libandroid_runtime.so'
    debugfs(chain_inputs['system'],f'dump /system/lib64/libandroid_runtime.so {runtime}')
    assert sha(runtime)==review['original_platform_runtime_sha256']==\
        '4ed3af57b6335c0e30fead26383ee7867bea9027695a9542b98297b3880221ec'
    # Existing r42 payload/policy/RRO nodes retain their original inode metadata.
    # Only these three native runtime files are newly added, in existing directories.
    nodes={rel:dict(uid=0,gid=0,mode=0o755 if rel=='bin/sheng-face' else 0o644,
                   mtime_ns=1230768000*1_000_000_000,
                   selinux='u:object_r:sheng_face_exec:s0' if rel=='bin/sheng-face' else 'u:object_r:system_file:s0')
           for rel in ['bin/sheng-face','framework/ShengNativeFaceBootstrap.jar','etc/init/sheng-face.rc']}
    outputs,trees,reports={},{},{}
    print('Staging native Face payload and system_ext policy',flush=True)
    outputs['system_ext'],trees['system_ext'],reports['system_ext']=stage_ext4(
        'system_ext',chain_inputs['system_ext'],entries['system_ext'],nodes,work,avb,avbtool,certificates(reference))
    for part in ['odm','vendor']:
        print('Staging native Face resources in '+part,flush=True)
        new_nodes = {'etc/vintf/manifest/face-native.xml': dict(uid=0,gid=0,mode=0o644,
            mtime_ns=1230768000*1_000_000_000,selinux='u:object_r:vendor_configs_file:s0')} if part=='odm' else {}
        outputs[part],trees[part],reports[part]=stage_erofs(part,chain_inputs[part],entries[part],new_nodes,work,avb,avbtool)
    for part in SCOPE:
        assert set(reports[part]['changed_files'])==set(SCOPE[part])
        assert reports[part]['metadata_preserved']
    # Check unchanged policy context/mapping inputs against the installed r42 base.
    base=work/'system_ext-before';after=work/'system_ext-after'
    for path in (base/'etc/selinux').rglob('*'):
        if path.is_file() and str(path.relative_to(base)) not in SCOPE['system_ext']:
            assert path.read_bytes()==(after/path.relative_to(base)).read_bytes(),path
    # Old ODM precompiled policy will be bypassed at boot due to the changed hash.
    assert (after/'etc/selinux/system_ext_sepolicy_and_mapping.sha256').read_bytes()!=\
        (work/'odm-tree/etc/selinux/precompiled_sepolicy.system_ext_sepolicy_and_mapping.sha256').read_bytes()
    boot_policy=verify_boot_policy(chain_inputs,work)
    vintf=verify_vintf(chain_inputs,work,args.runtime_vintf)
    outputs['vbmeta_system']=work/'vbmeta_system.img'
    merge_parent(avb,avbtool,chain_inputs['vbmeta_system'],[trees['system_ext']],outputs['vbmeta_system'],'SHA256_RSA2048',work)
    outputs['vbmeta']=work/'vbmeta.img'
    merge_parent(avb,avbtool,chain_inputs['vbmeta'],[trees['odm'],trees['vendor']],outputs['vbmeta'],'SHA256_RSA4096',work)
    chain=work/'complete-chain';chain.mkdir()
    for part,path in chain_inputs.items(): (chain/(part+'.img')).symlink_to(outputs.get(part,path).resolve())
    r=subprocess.run([HOST/'avbtool','verify_image','--image',chain/'vbmeta.img','--follow_chain_partitions'],text=True,capture_output=True)
    (work/'complete-chain.avb.txt').write_text(r.stdout+r.stderr);assert r.returncode==0,r.stdout+r.stderr
    for rel,digest in review['sources_sha256'].items(): assert sha(workspace/rel)==sha(ROM/rel)==digest,rel
    for part in SCOPE:validate_inputs(part,entries[part])
    validate_packaging_inputs(SCOPE,frozen)
    assert {part:sha(chain_inputs[part]) for part in BASELINE}==BASELINE
    evidence=workspace/'reports/device/20261110-resume/face-native/r44-package';evidence.mkdir(exist_ok=False)
    for path in work.iterdir():
        if path.is_file() and path.suffix in ['.log','.txt','.json']:shutil.copyfile(path,evidence/path.name)
    publish_batch(destination,outputs,dict(revision=44,baseline_sha256=BASELINE,
        build_review_sha256=sha(args.build_review),post_audit_sha256=sha(args.post_audit),
        source_commit=subprocess.check_output(['git','-C',workspace,'rev-parse','HEAD'],text=True).strip(),
        entries=entries,partition_reports=reports,packaging_inputs=frozen,boot_policy=boot_policy,vintf=vintf,all_filesystem_stages_verified=True,
        complete_avb_chain_verified=True,original_systemui_unchanged=True,normal_module_build_passed=True,
        full_product_build_passed=False,native_manifest_without_app_components=True,
        api1_runtime_tested=False,hardware_boot_tested=False,native_settings_enrollment_tested=False,
        keyguard_authentication_tested=False,persistent_build_evidence_dir=str(evidence),work_dir=str(work)))
    print(destination,flush=True)

if __name__=='__main__':main()
