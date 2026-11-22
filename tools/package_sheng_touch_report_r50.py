#!/usr/bin/env python3
"""Seal the device-owned THP report switch over the verified installed r49 chain."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile
from package_sheng_batch_helpers import (certificates, debugfs, erofs_input_keys,
    merge_parent, packaging_input_path, publish_batch, stage_erofs, stage_ext4,
    validate_inputs, validate_packaging_inputs, verify_boot_policy, verify_vintf)
from package_sheng_model_followup import HOST, PRODUCT, ROM, sha

ORIGINAL_THP = 'cb75e8cf9128f9ea6177d8276d440dc16f55db8f068f7644e94668cfc8f6e2c5'
ORIGINAL_UI = '33017b0d59e28da5db3e089a98f49601de508228a012392ee2d04c82cda3ccb1'

def resource_values(text):
    blocks = re.split(r'(?m)^\s*resource ', text)[1:]
    result = {}
    for block in blocks:
        # aapt2 places the next type's heading between resource blocks. Adding
        # string resources changes that heading; it is not a resource value.
        block = re.split(r'(?m)^\s*type\s+', block)[0]
        name = re.match(r'0x[0-9a-f]+\s+(\S+)', block)[1]
        if name.rsplit('/', 1)[-1] in ['high_touch_polling_rate_title', 'high_touch_polling_rate_summary']:
            continue
        result[name] = re.sub(r'0x[0-9a-fA-F]{8}', 'RESOURCE_ID', block).strip()
    assert result
    return result

def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'build-log', 'audit', 'mirror', 'work', 'runtime-vintf']:
        p.add_argument('--'+name, type=Path, required=True)
    args = p.parse_args()
    workspace = args.workspace.resolve(strict=True)
    work = args.work
    work.mkdir(exist_ok=False)
    assert shutil.disk_usage(work).free > 8*1024**3
    assert '#### build completed successfully' in args.build_log.read_text()
    audit, mirror = json.loads(args.audit.read_text()), json.loads(args.mirror.read_text())
    assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
    assert datetime.now(timezone.utc).timestamp()-datetime.fromisoformat(audit['date_utc']).timestamp() < 7200
    assert mirror['passed'] and 'interfaces/input/touch' in mirror['scopes']
    def check_sources():
        for name, entry in mirror['inputs'].items():
            assert entry['kind'] == 'file' and sha(workspace/name) == sha(ROM/name) == entry['sha256'], name
    check_sources()
    commands = []
    def run(argv):
        value = subprocess.run(list(map(str, argv)), text=True, capture_output=True)
        commands.append(dict(argv=list(map(str, argv)), returncode=value.returncode,
                             stdout=value.stdout, stderr=value.stderr))
        (work/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
        assert value.returncode == 0, value.stdout+value.stderr
        return value.stdout
    previous = json.loads((workspace/'artifacts/system-hardware-followup-sheng-r49/build-result.json').read_text())
    assert previous['complete_avb_chain_verified'] and previous['original_thp_restored']
    digests = {e['partition']:e['sha256'] for e in json.loads(
        (workspace/'reports/device/r38-restore-20261110/restore-manifest.json').read_text())['files']}
    for revision in [39,40,41,42,44,45,48,49]:
        report = json.loads((workspace/f'artifacts/system-hardware-followup-sheng-r{revision}/build-result.json').read_text())
        for entry in report['files']:
            digests[entry['partition']] = entry['sha256']
    cache = Path(previous['work_dir'])/'complete-chain'
    chain = {part:cache/(part+'.img') for part in digests}
    assert all(sha(path) == digests[part] for part,path in chain.items())
    base_ext = work/'baseline-system-ext'
    base_ext.mkdir()
    debugfs(chain['system_ext'], f'rdump / {base_ext}')
    reference = base_ext/'priv-app/SystemUI/SystemUI.apk'
    assert sha(reference) == ORIGINAL_UI
    policy_before = (base_ext/'etc/selinux/system_ext_sepolicy.cil').read_text()
    policy_after = (PRODUCT/'system_ext/etc/selinux/system_ext_sepolicy.cil').read_text()
    assert 'sheng_face_key' not in policy_after
    face_rules = lambda value: {x for x in value.splitlines() if x.startswith('(allow sheng_face ')}
    assert face_rules(policy_before) == face_rules(policy_after)
    scope = {
        'system_ext': ['priv-app/ShengTouch/ShengTouch.apk',
            'etc/selinux/system_ext_sepolicy.cil', 'etc/selinux/system_ext_sepolicy_and_mapping.sha256'],
        'vendor': ['bin/hw/vendor.lineage.touch-service.sheng',
            'etc/init/vendor.lineage.touch-service.xiaomi.rc',
            'etc/vintf/manifest/vendor.lineage.touch-service.xiaomi-htpr.xml',
            'etc/selinux/vendor_sepolicy.cil', 'etc/selinux/vendor_file_contexts',
            'etc/selinux/vendor_property_contexts', 'etc/selinux/plat_pub_versioned.cil'],
        'odm': ['overlay/SettingsResOverlaySheng.apk'],
        'product': ['etc/selinux/product_sepolicy.cil', 'etc/selinux/product_sepolicy_and_mapping.sha256'],
    }
    installed_sources = {'vendor': {
        'etc/init/vendor.lineage.touch-service.xiaomi.rc': 'etc/init/vendor.lineage.touch-service.sheng.rc',
        'etc/vintf/manifest/vendor.lineage.touch-service.xiaomi-htpr.xml':
            'etc/vintf/manifest/vendor.lineage.touch-service.sheng.xml',
    }}
    # This scoped update replaces the existing init/manifest slots so it cannot
    # start/register both services. Full product builds use the new unique paths.
    entries = {}
    for part, names in scope.items():
        entries[part] = {}
        for name in names:
            source = PRODUCT/part/installed_sources.get(part, {}).get(name, name)
            assert source.is_file() and not source.is_symlink(), source
            entries[part][name] = dict(source=str(source), kind='file', bytes=source.stat().st_size, sha256=sha(source))
            if name.endswith('.apk'):
                run([HOST/'apksigner','verify',source])
                run([HOST/'zipalign','-c','-P','16','4',source])
        validate_inputs(part, entries[part], installed_sources=installed_sources.get(part))
    touch = PRODUCT/'system_ext/priv-app/ShengTouch/ShengTouch.apk'
    assert certificates(touch) == certificates(reference)
    assert "versionCode='2'" in run([HOST/'aapt2','dump','badging',touch])
    manifest = run([HOST/'aapt2','dump','xmltree',touch,'--file','AndroidManifest.xml'])
    assert all(value in manifest for value in ['android.uid.system','persistent','directBootAware'])
    assert not any(value in manifest for value in ['E: activity','E: service','CAMERA'])
    with zipfile.ZipFile(touch) as archive:
        native = archive.getinfo('lib/arm64-v8a/libsheng_touch_jni.so')
        assert native.compress_type == zipfile.ZIP_STORED
        compiled = list((ROM/'out/soong/.intermediates/device/xiaomi/sheng/interfaces/input/touch/libsheng_touch_jni').glob(
            'android_arm64_*_shared/libsheng_touch_jni.so'))
        assert len(compiled) == 1 and archive.read(native) == compiled[0].read_bytes()
        native_hash = sha(compiled[0])
    assert sha(PRODUCT/'odm/firmware/n81a_nova_thp_config.ini') == ORIGINAL_THP
    hal = PRODUCT/'vendor/bin/hw/vendor.lineage.touch-service.sheng'
    assert b'IHighTouchPollingRate' in hal.read_bytes()
    needed = run(['/usr/bin/readelf','-d',hal])
    assert all(name in needed for name in ['libbase.so','libbinder_ndk.so','vendor.lineage.touch-V1-ndk.so'])
    run([ROM/'out/host/linux-x86/nativetest64/sheng_touch_control_test/sheng_touch_control_test'])
    frozen = {key:sha(packaging_input_path(key)) for key in
              set().union(*(erofs_input_keys(part) for part in ['odm','vendor']))}
    validate_packaging_inputs(scope, frozen)
    sys.path.insert(0, str(ROM/'external/avb'))
    import avbtool
    avb = avbtool.Avb()
    outputs, trees, reports = {}, {}, {}
    outputs['system_ext'], trees['system_ext'], reports['system_ext'] = stage_ext4(
        'system_ext', chain['system_ext'], entries['system_ext'], {}, work, avb, avbtool,
        certificates(reference), replacement_mtimes={'priv-app/ShengTouch/ShengTouch.apk':1230768050})
    # A freshly generated matching product policy is included only if changed.
    base_product = work/'baseline-product'
    base_product.mkdir()
    debugfs(chain['product'], f'rdump /etc/selinux {base_product}')
    product_changed = any(sha(base_product/'selinux'/Path(name).name) != entry['sha256']
                          for name, entry in entries['product'].items())
    if product_changed:
        outputs['product'], trees['product'], reports['product'] = stage_ext4(
            'product',chain['product'],entries['product'],{},work,avb,avbtool,certificates(reference))
    else:
        del entries['product']
    for part in ['vendor','odm']:
        print('Staging '+part, flush=True)
        nodes = {'bin/hw/vendor.lineage.touch-service.sheng':
            dict(uid=0,gid=0,mode=0o755,mtime_ns=1230768048*1_000_000_000,
                 selinux='u:object_r:hal_lineage_touch_default_exec:s0')} if part == 'vendor' else {}
        outputs[part], trees[part], reports[part] = stage_erofs(
            part,chain[part],entries[part],nodes,work,avb,avbtool,
            installed_sources=installed_sources.get(part))
        assert reports[part]['metadata_preserved']
        assert set(reports[part]['changed_files']) <= set(scope[part])
    after = work/'system_ext-after'
    assert sha(after/'priv-app/SystemUI/SystemUI.apk') == ORIGINAL_UI
    old_overlay = work/'odm-tree/overlay/SettingsResOverlaySheng.apk'
    # stage_erofs records the baseline byte identity; inspect it from the cached
    # r49 extracted tree after verifying that exact r49 image above.
    baseline_overlay = Path(previous['work_dir'])/'odm-tree/overlay/SettingsResOverlaySheng.apk'
    assert sha(baseline_overlay) == '683700b6dd013d96ceae0a42c824c1d2fb316b2ef032e96429d61714d39926f0'
    before_values = resource_values(run([HOST/'aapt2','dump','resources',baseline_overlay]))
    after_values = resource_values(run([HOST/'aapt2','dump','resources',old_overlay]))
    assert before_values == after_values, 'Unrelated Settings overlay resources changed'
    run([HOST/'idmap2','create','--target-apk-path',after/'priv-app/Settings/Settings.apk',
        '--overlay-apk-path',old_overlay,'--idmap-path',work/'Settings.idmap',
        '--policy','public','--policy','odm','--policy','signature'])
    assert (after/'etc/selinux/system_ext_sepolicy_and_mapping.sha256').read_bytes() != (
        work/'odm-tree/etc/selinux/precompiled_sepolicy.system_ext_sepolicy_and_mapping.sha256').read_bytes()
    combination = {**chain, **outputs}
    boot_policy = verify_boot_policy(combination, work)
    selected = [work/name for name in boot_policy['input_sha256']]
    run([HOST/'secilc',selected[0],'-m','-M','true','-G','-c','30',selected[1],
         '-o',work/'combined-policy-strict','-f','/dev/null',*selected[2:]])
    boot_policy['actual_partition_neverallows_passed'] = True
    vintf = verify_vintf(combination,work,args.runtime_vintf)
    for part, algorithm, children in [('vbmeta_system','SHA256_RSA2048',['system_ext','product']),
                                      ('vbmeta','SHA256_RSA4096',['vendor','odm'])]:
        outputs[part] = work/(part+'.img')
        merge_parent(avb,avbtool,chain[part],[trees[child] for child in children if child in trees],
                     outputs[part],algorithm,work)
    complete = work/'complete-chain'
    complete.mkdir()
    for part,path in chain.items():
        (complete/(part+'.img')).symlink_to(outputs.get(part,path).resolve())
    run([HOST/'avbtool','verify_image','--image',complete/'vbmeta.img','--follow_chain_partitions'])
    check_sources()
    for part, value in entries.items():
        validate_inputs(part, value, installed_sources=installed_sources.get(part))
    validate_packaging_inputs(scope,frozen)
    current_parts = ['odm','vendor','product','system_ext','vbmeta','vbmeta_system']
    unchanged = [dict(partition=part,name=part+'.img',bytes=chain[part].stat().st_size,sha256=digests[part])
                 for part in current_parts if part not in outputs]
    publish_batch(workspace/'artifacts/system-hardware-followup-sheng-r50',outputs,dict(
        revision=50,baseline_revision=49,baseline_sha256={part:digests[part] for part in current_parts},
        unchanged_partition_files=unchanged,entries=entries,partition_reports=reports,
        installed_source_mappings=installed_sources,
        boot_policy=boot_policy,vintf=vintf,original_systemui_unchanged=True,
        complete_avb_chain_verified=True,all_filesystem_stages_verified=True,normal_module_build_passed=True,
        full_product_build_passed=False,high_touch_report_only=True,high_touch_report_mode=202,
        physical_scan_360_fixed=False,face_r46_installed=False,original_thp_sha256=ORIGINAL_THP,
        unrelated_settings_overlay_resources_preserved=True,touch_embedded_jni_sha256=native_hash,
        product_policy_changed=product_changed,hardware_boot_tested=False,
        sources_sha256={name:e['sha256'] for name,e in mirror['inputs'].items()},
        build_log_sha256=sha(args.build_log),source_mirror_sha256=sha(args.mirror),post_audit_sha256=sha(args.audit),
        packaging_inputs=frozen,work_dir=str(work),
        source_commit=subprocess.check_output(['git','-C',workspace,'rev-parse','HEAD'],text=True).strip()))
    print('Published r50',flush=True)

if __name__ == '__main__': main()
