#!/usr/bin/env python3
"""Seal only the normally built Dolby switch APK over the installed r50 chain."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from package_sheng_batch_helpers import certificates, debugfs, merge_parent, publish_batch, stage_ext4, validate_inputs
from package_sheng_model_followup import HOST, PRODUCT, ROM, sha

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'build-log', 'audit', 'mirror', 'work']:
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve(strict=True)
    work = args.work
    work.mkdir(exist_ok=False)
    assert shutil.disk_usage(work).free > 4*1024**3
    assert '#### build completed successfully' in args.build_log.read_text()
    audit, mirror = [json.loads(p.read_text()) for p in [args.audit, args.mirror]]
    assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
    assert datetime.now(timezone.utc).timestamp()-datetime.fromisoformat(audit['date_utc']).timestamp()<7200
    assert mirror['passed'] and mirror['scopes']==['dolby/ShengDolby']
    def sources():
        for name, entry in mirror['inputs'].items():
            assert entry['kind']=='file' and sha(workspace/name)==sha(ROM/name)==entry['sha256'],name
    sources()
    previous = json.loads((workspace/'artifacts/system-hardware-followup-sheng-r50/build-result.json').read_text())
    assert previous['complete_avb_chain_verified'] and previous['original_systemui_unchanged']
    assert previous['boot_policy']['actual_partition_neverallows_passed']
    assert previous['vintf']['actual_partition_combination_compatible']
    digests = {e['partition']: e['sha256'] for e in json.loads(
        (workspace/'reports/device/r38-restore-20261110/restore-manifest.json').read_text())['files']}
    for revision in [39,40,41,42,44,45,48,49,50]:
        report=json.loads((workspace/f'artifacts/system-hardware-followup-sheng-r{revision}/build-result.json').read_text())
        assert report['complete_avb_chain_verified']
        for entry in report['files']: digests[entry['partition']]=entry['sha256']
    cache=Path(previous['work_dir'])/'complete-chain'
    chain={part:cache/(part+'.img') for part in digests}
    assert all(sha(path)==digests[part] for part,path in chain.items())
    commands=[]
    def run(argv):
        result=subprocess.run(list(map(str,argv)),capture_output=True,text=True)
        commands.append(dict(argv=list(map(str,argv)),returncode=result.returncode,stdout=result.stdout,stderr=result.stderr))
        (work/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        assert result.returncode==0,result.stdout+result.stderr
        return result.stdout
    relative='priv-app/ShengDolby/ShengDolby.apk'
    apk=PRODUCT/'system_ext'/relative
    run([HOST/'apksigner','verify','--min-sdk-version','1',apk])
    run([HOST/'zipalign','-c','-P','16','4',apk])
    assert "versionCode='51'" in run([HOST/'aapt2','dump','badging',apk])
    manifest=run([HOST/'aapt2','dump','xmltree',apk,'--file','AndroidManifest.xml'])
    assert all(s in manifest for s in ['com.android.settings.action.EXTRA_SETTINGS','android.media.action.DISPLAY_AUDIO_EFFECT_CONTROL_PANEL','persistent','directBootAware'])
    assert 'android.intent.category.LAUNCHER' not in manifest and 'CAMERA' not in manifest
    with zipfile.ZipFile(apk) as archive:
        assert all(archive.read(name)[:8]==b'dex\n035\0' for name in archive.namelist() if name.endswith('.dex'))
    reference=work/'SystemUI-reference.apk'
    debugfs(chain['system_ext'],f'dump /priv-app/SystemUI/SystemUI.apk {reference}')
    ui_hash='33017b0d59e28da5db3e089a98f49601de508228a012392ee2d04c82cda3ccb1'
    assert sha(reference)==ui_hash and certificates(apk)==certificates(reference)
    entries={relative:dict(source=str(apk),kind='file',bytes=apk.stat().st_size,sha256=sha(apk))}
    validate_inputs('system_ext',entries)
    sys.path.insert(0,str(ROM/'external/avb'))
    import avbtool
    avb=avbtool.Avb()
    image,tree,report=stage_ext4('system_ext',chain['system_ext'],entries,{},work,avb,avbtool,certificates(reference))
    assert report['changed_files']==[relative] and report['metadata_preserved'] and not report['created_nodes']
    assert sha(work/'system_ext-after/priv-app/SystemUI/SystemUI.apk')==ui_hash
    outputs=dict(system_ext=image,vbmeta_system=work/'vbmeta_system.img')
    merge_parent(avb,avbtool,chain['vbmeta_system'],[tree],outputs['vbmeta_system'],'SHA256_RSA2048',work)
    complete=work/'complete-chain'
    complete.mkdir()
    for part,path in chain.items(): (complete/(part+'.img')).symlink_to(outputs.get(part,path).resolve())
    run([HOST/'avbtool','verify_image','--image',complete/'vbmeta.img','--follow_chain_partitions'])
    sources()
    validate_inputs('system_ext',entries)
    parts=['odm','product','system_ext','vendor','vbmeta','vbmeta_system']
    unchanged=[dict(partition=p,name=p+'.img',bytes=chain[p].stat().st_size,sha256=digests[p]) for p in parts if p not in outputs]
    publish_batch(workspace/'artifacts/system-hardware-followup-sheng-r51',outputs,dict(
        revision=51,baseline_revision=50,baseline_sha256={p:digests[p] for p in parts},
        unchanged_partition_files=unchanged,entries={'system_ext':entries},partition_reports={'system_ext':report},
        original_systemui_unchanged=True,complete_avb_chain_verified=True,all_filesystem_stages_verified=True,
        normal_module_build_passed=True,full_product_build_passed=False,hardware_boot_tested=False,
        policy_and_vintf_unchanged=True,touch_r50_retained=True,dolby_oem_libraries_unchanged=True,
        dolby_switch_clickability_fixed=True,eq_requires_custom_profile=True,cross_app_audio_fixed=False,
        sources_sha256={n:e['sha256'] for n,e in mirror['inputs'].items()},
        build_log_sha256=sha(args.build_log),source_mirror_sha256=sha(args.mirror),post_audit_sha256=sha(args.audit),
        work_dir=str(work),source_commit=subprocess.check_output(['git','-C',workspace,'rev-parse','HEAD'],text=True).strip()))
    print('Published r51',flush=True)

if __name__=='__main__': main()
