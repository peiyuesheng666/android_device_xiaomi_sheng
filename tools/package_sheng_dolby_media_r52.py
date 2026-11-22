#!/usr/bin/env python3
"""Seal the normally built media-routing property over the installed r51 chain."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
from package_sheng_batch_helpers import debugfs, merge_parent, publish_batch, stage_erofs, validate_inputs
from package_sheng_model_followup import HOST, PRODUCT, ROM, sha


def properties(path):
    result = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        # Preserve all original occurrences, including legacy duplicated keys.
        result.setdefault(key, []).append(value)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'build-log', 'audit', 'mirror', 'work']:
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    assert __debug__
    workspace = args.workspace.resolve(strict=True)
    work = args.work
    work.mkdir(exist_ok=False)
    assert shutil.disk_usage(work).free > 4*1024**3
    assert '#### build completed successfully' in args.build_log.read_text()
    assert (HOST/'soong_build').read_bytes()[:4] == b'\x7fELF'
    audit, mirror = [json.loads(p.read_text()) for p in [args.audit, args.mirror]]
    assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
    assert datetime.now(timezone.utc).timestamp()-datetime.fromisoformat(audit['date_utc']).timestamp() < 7200
    assert mirror['passed'] and mirror['scopes'] == ['properties/vendor.prop']

    def sources():
        for name, entry in mirror['inputs'].items():
            assert entry['kind'] == 'file' and sha(workspace/name) == sha(ROM/name) == entry['sha256'], name
    sources()
    previous = json.loads((workspace/'artifacts/system-hardware-followup-sheng-r51/build-result.json').read_text())
    assert previous['complete_avb_chain_verified'] and previous['original_systemui_unchanged']
    digests = {e['partition']: e['sha256'] for e in json.loads(
        (workspace/'reports/device/r38-restore-20261110/restore-manifest.json').read_text())['files']}
    for revision in [39,40,41,42,44,45,48,49,50,51]:
        report = json.loads((workspace/f'artifacts/system-hardware-followup-sheng-r{revision}/build-result.json').read_text())
        assert report['complete_avb_chain_verified']
        for entry in report['files']:
            digests[entry['partition']] = entry['sha256']
    cache = Path(previous['work_dir'])/'complete-chain'
    chain = {part: cache/(part+'.img') for part in digests}
    assert all(sha(path) == digests[part] for part,path in chain.items())
    commands = []

    def run(argv):
        result = subprocess.run(list(map(str,argv)),capture_output=True,text=True)
        commands.append(dict(argv=list(map(str,argv)),returncode=result.returncode,stdout=result.stdout,stderr=result.stderr))
        (work/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        assert result.returncode == 0, result.stdout+result.stderr
        return result.stdout

    reference = work/'SystemUI-reference.apk'
    debugfs(chain['system_ext'],f'dump /priv-app/SystemUI/SystemUI.apk {reference}')
    assert sha(reference) == '33017b0d59e28da5db3e089a98f49601de508228a012392ee2d04c82cda3ccb1'
    baseline = work/'baseline-vendor'
    run([HOST/'fsck.erofs','-d0','--extract='+str(baseline),'--preserve',chain['vendor']])
    prop = PRODUCT/'vendor/build.prop'
    before, after = properties(baseline/'build.prop'), properties(prop)
    assert before.keys() == after.keys()
    changed = {key for key in before if before[key] != after[key]}
    assert 'audio.deep_buffer.media' in changed
    assert changed <= {'audio.deep_buffer.media','ro.vendor.build.uuid'}, changed
    assert before['audio.deep_buffer.media'] == ['false'] and after['audio.deep_buffer.media'] == ['true']
    assert after['ro.vendor.build.date.utc'] == ['1794387709']
    assert all(len(before[key]) == len(after[key]) == 1 for key in changed)
    entries = {'build.prop': dict(source=str(prop),kind='file',bytes=prop.stat().st_size,sha256=sha(prop))}
    validate_inputs('vendor',entries)
    sys.path.insert(0,str(ROM/'external/avb'))
    import avbtool
    avb = avbtool.Avb()
    image, tree, stage = stage_erofs('vendor',chain['vendor'],entries,{},work,avb,avbtool)
    assert stage['changed_files'] == ['build.prop'] and stage['metadata_preserved']
    outputs = dict(vendor=image,vbmeta=work/'vbmeta.img')
    merge_parent(avb,avbtool,chain['vbmeta'],[tree],outputs['vbmeta'],'SHA256_RSA4096',work)
    complete = work/'complete-chain'
    complete.mkdir()
    for part,path in chain.items():
        (complete/(part+'.img')).symlink_to(outputs.get(part,path).resolve())
    run([HOST/'avbtool','verify_image','--image',complete/'vbmeta.img','--follow_chain_partitions'])
    sources()
    validate_inputs('vendor',entries)
    parts = ['odm','product','system_ext','vendor','vbmeta','vbmeta_system']
    unchanged = [dict(partition=p,name=p+'.img',bytes=chain[p].stat().st_size,sha256=digests[p]) for p in parts if p not in outputs]
    publish_batch(workspace/'artifacts/system-hardware-followup-sheng-r52',outputs,dict(
        revision=52,baseline_revision=51,baseline_sha256={p:digests[p] for p in parts},
        unchanged_partition_files=unchanged,entries={'vendor':entries},partition_reports={'vendor':stage},
        changed_properties={key:dict(before=before[key][0],after=after[key][0]) for key in sorted(changed)},
        original_systemui_unchanged=True,complete_avb_chain_verified=True,all_filesystem_stages_verified=True,
        normal_property_build_passed=True,full_product_build_passed=False,hardware_boot_tested=False,
        policy_and_vintf_unchanged=True,touch_r50_retained=True,dolby_ui_r51_retained=True,
        dolby_oem_libraries_unchanged=True,standard_media_deep_buffer_enabled=True,
        explicit_fast_mmap_voice_routing_unchanged=True,
        douyin_temporary_audio_user_accepted=True,cross_app_audio_after_reboot_tested=False,
        sources_sha256={n:e['sha256'] for n,e in mirror['inputs'].items()},
        build_log_sha256=sha(args.build_log),source_mirror_sha256=sha(args.mirror),post_audit_sha256=sha(args.audit),
        work_dir=str(work),source_commit=subprocess.check_output(['git','-C',workspace,'rev-parse','HEAD'],text=True).strip()))
    print('Published r52',flush=True)


if __name__ == '__main__':
    main()
