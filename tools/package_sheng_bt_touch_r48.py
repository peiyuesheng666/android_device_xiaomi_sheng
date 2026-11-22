#!/usr/bin/env python3
"""Seal the four functional device-tree repairs over the installed r45 chain."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

from package_sheng_batch_helpers import (certificates, contents, debugfs,
    erofs_input_keys, merge_parent, packaging_input_path, publish_batch,
    stage_erofs, stage_ext4, validate_inputs, validate_packaging_inputs,
    verify_boot_policy, verify_vintf)
from package_sheng_model_followup import HOST, PRODUCT, ROM, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'build-log', 'audit', 'mirror', 'work', 'runtime-vintf']:
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    assert __debug__
    workspace = args.workspace.resolve(strict=True)
    args.work.mkdir(exist_ok=False)
    work = args.work
    assert shutil.disk_usage(work).free > 15 * 1024**3
    assert '#### build completed successfully' in args.build_log.read_text()
    assert (ROM/'out/host/linux-x86/bin/soong_build').read_bytes()[:4] == b'\x7fELF'
    audit, mirror = json.loads(args.audit.read_text()), json.loads(args.mirror.read_text())
    assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
    assert datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(audit['date_utc']).timestamp() < 7200
    assert mirror['passed'] and 'properties/vendor.prop' in mirror['scopes']
    def check_sources():
        for name, entry in mirror['inputs'].items():
            assert entry['kind'] == 'file'
            assert sha(workspace/name) == sha(ROM/name) == entry['sha256'], name
    check_sources()
    commands = []
    def run(argv):
        r = subprocess.run(list(map(str, argv)), capture_output=True, text=True)
        commands.append(dict(argv=list(map(str, argv)), returncode=r.returncode,
                             stdout=r.stdout, stderr=r.stderr))
        (work/'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        assert r.returncode == 0, r.stdout + r.stderr
        return r.stdout
    # Reconstruct manifest digests, then use byte-verified local r45 caches.
    restored = json.loads((workspace/'reports/device/r38-restore-20261110/restore-manifest.json').read_text())
    assert restored['complete_avb_chain_verified']
    digests = {e['partition']: e['sha256'] for e in restored['files']}
    for revision in [39, 40, 41, 42, 44, 45]:
        previous = json.loads((workspace/f'artifacts/system-hardware-followup-sheng-r{revision}/build-result.json').read_text())
        assert previous['complete_avb_chain_verified'] and previous['original_systemui_unchanged']
        for entry in previous['files']:
            digests[entry['partition']] = entry['sha256']
    cached = Path('/root/sheng-lineage/hardware-diagnostics/sheng-simple-r47-20261111/package')
    chain = {part: cached/f'base-{part}.img' for part in digests}
    assert all(sha(path) == digests[part] for part, path in chain.items())
    reference = work/'original-SystemUI.apk'
    debugfs(chain['system_ext'], f'dump /priv-app/SystemUI/SystemUI.apk {reference}')
    assert sha(reference) == '33017b0d59e28da5db3e089a98f49601de508228a012392ee2d04c82cda3ccb1'
    # Review against actual installed policy, not the uninstalled face r46 output.
    ext = work/'policy-baseline'
    ext.mkdir()
    debugfs(chain['system_ext'], f'rdump /etc/selinux {ext}')
    base_policy = (ext/'selinux/system_ext_sepolicy.cil').read_text()
    new_policy = (PRODUCT/'system_ext/etc/selinux/system_ext_sepolicy.cil').read_text()
    assert 'sheng_touch_app' in new_policy and 'sheng_face_key' not in new_policy
    face_rules = lambda data: {line for line in data.splitlines() if line.startswith('(allow sheng_face ')}
    assert face_rules(base_policy) == face_rules(new_policy), 'Deferred face rules changed'
    scope = {
        'odm': ['overlay/FrameworkResOverlaySheng.apk', 'overlay/LineageResOverlaySheng.apk',
                'firmware/n81a_nova_thp_config.ini'],
        'vendor': ['etc/audio/sku_kalama/audio_policy_configuration.xml', 'build.prop',
                   'bin/sheng-touchctl', 'etc/init/init.sheng.touch.rc',
                   'etc/selinux/vendor_file_contexts', 'etc/selinux/vendor_sepolicy.cil',
                   'etc/selinux/plat_pub_versioned.cil'],
        'system_ext': ['priv-app/ShengDisplayDefaults/ShengDisplayDefaults.apk',
                       'priv-app/ShengTouch/ShengTouch.apk',
                       'etc/permissions/privapp-permissions-com.xiaomi.sheng.touch.xml',
                       'etc/selinux/system_ext_sepolicy.cil',
                       'etc/selinux/system_ext_sepolicy_and_mapping.sha256',
                       'etc/selinux/system_ext_seapp_contexts'],
        'product': ['etc/selinux/product_sepolicy.cil',
                    'etc/selinux/product_sepolicy_and_mapping.sha256'],
    }
    # Public system_ext exports require their generated version mappings.
    for path in sorted((PRODUCT/'system_ext/etc/selinux/mapping').glob('*.cil')):
        scope['system_ext'].append(path.relative_to(PRODUCT/'system_ext').as_posix())
    entries = {}
    for part, paths in scope.items():
        entries[part] = {}
        for relative in paths:
            path = PRODUCT/part/relative
            assert path.is_file() and not path.is_symlink(), path
            entries[part][relative] = dict(source=str(path), kind='file',
                bytes=path.stat().st_size, sha256=sha(path))
            if relative.endswith('.apk'):
                run([HOST/'zipalign', '-c', '-P', '16', '4', path])
        validate_inputs(part, entries[part])
    touch = PRODUCT/'system_ext/priv-app/ShengTouch/ShengTouch.apk'
    assert certificates(touch) == certificates(reference)
    manifest = run([HOST/'aapt2', 'dump', 'xmltree', touch, '--file', 'AndroidManifest.xml'])
    for value in ['android.uid.system', 'persistent', 'directBootAware']:
        assert value in manifest, value
    assert not any(value in manifest for value in ['E: activity', 'E: service', 'CAMERA'])
    with zipfile.ZipFile(touch) as archive:
        native = archive.getinfo('lib/arm64-v8a/libsheng_touch_jni.so')
        assert native.compress_type == zipfile.ZIP_STORED
        native_outputs = list((ROM/'out/soong/.intermediates/device/xiaomi/sheng/interfaces/input/touch/libsheng_touch_jni').glob(
            'android_arm64_*_shared/libsheng_touch_jni.so'))
        assert len(native_outputs) == 1, native_outputs
        assert archive.read(native) == native_outputs[0].read_bytes()
        native_sha256 = sha(native_outputs[0])
    defaults = run([HOST/'aapt2', 'dump', 'badging', PRODUCT/'system_ext'/scope['system_ext'][0]])
    assert "versionCode='2'" in defaults
    for name, target, keys, expected in [
        ('FrameworkResOverlaySheng', 'framework-res.apk',
         ['config_defaultRefreshRate', 'config_defaultPeakRefreshRate'], 144),
        ('LineageResOverlaySheng', 'org.lineageos.platform-res.apk',
         ['config_buttonBrightnessSettingDefaultFloat', 'config_keyboardBrightnessSettingDefaultFloat'], 0)]:
        apk = PRODUCT/'odm/overlay'/(name+'.apk')
        resources = run([HOST/'aapt2', 'dump', 'resources', apk])
        for key in keys:
            value = re.search(r'(?m)^\s*resource [^\n]*\b'+key+r'\b[^\n]*\n([^\n]*)', resources)
            assert value and float(value[1].strip().split()[-1]) == expected, key
        run([HOST/'idmap2', 'create', '--target-apk-path', PRODUCT/'system/framework'/target,
             '--overlay-apk-path', apk, '--idmap-path', work/(name+'.idmap'),
             '--policy', 'public', '--policy', 'odm', '--policy', 'signature'])
    assert 'vendor.usb.rndis.func.name=rndis\n' in (PRODUCT/'vendor/build.prop').read_text()
    audio = (PRODUCT/'vendor'/scope['vendor'][0]).read_text()
    assert 'AUDIO_FORMAT_LHDC' not in audio and 'bluetooth_qti_audio_policy_configuration.xml' in audio
    original_thp = workspace/'reports/device/20261111-simple/thp-config-before.ini'
    assert sha(original_thp) == 'cb75e8cf9128f9ea6177d8276d440dc16f55db8f068f7644e94668cfc8f6e2c5'
    assert (PRODUCT/'odm/firmware/n81a_nova_thp_config.ini').read_bytes() == original_thp.read_bytes().replace(
        b'rate_normal=120', b'rate_normal=240')
    frozen = {key: sha(packaging_input_path(key)) for key in
              set().union(*(erofs_input_keys(part) for part in ['odm', 'vendor']))}
    validate_packaging_inputs(scope, frozen)
    sys.path.insert(0, str(ROM/'external/avb'))
    import avbtool
    avb = avbtool.Avb()
    def node(context='system_file', executable=False):
        return dict(uid=0, gid=0, mode=0o755 if executable else 0o644,
                    mtime_ns=1230768048*1_000_000_000, selinux=f'u:object_r:{context}:s0')
    ext_nodes = {
        'priv-app/ShengTouch': node(executable=True),
        'priv-app/ShengTouch/ShengTouch.apk': node(),
        'etc/permissions/privapp-permissions-com.xiaomi.sheng.touch.xml': node(),
    }
    outputs, trees, reports = {}, {}, {}
    print('Staging system_ext', flush=True)
    outputs['system_ext'], trees['system_ext'], reports['system_ext'] = stage_ext4(
        'system_ext', chain['system_ext'], entries['system_ext'], ext_nodes, work,
        avb, avbtool, certificates(reference),
        replacement_mtimes={scope['system_ext'][0]: 1230768048})
    print('Staging matching generated product policy', flush=True)
    outputs['product'], trees['product'], reports['product'] = stage_ext4(
        'product', chain['product'], entries['product'], {}, work,
        avb, avbtool, certificates(reference))
    old_product = (work/'product-before/etc/selinux/product_sepolicy.cil').read_text()
    new_product = (work/'product-after/etc/selinux/product_sepolicy.cil').read_text()
    # checkpolicy numbers generated attributes across split partitions. Adding
    # the app changes subsequent product numbers; verify only this renumbering.
    attrs = lambda text: dict(re.findall(r'(?m)^\(typeattributeset (base_typeattr_\d+) (.+)\)$', text))
    old_attrs, new_attrs = attrs(old_product), attrs(new_product)
    assert len(set(new_attrs.values())) == len(new_attrs)
    assert set(old_attrs.values()) == set(new_attrs.values())
    by_expression = {value:key for key,value in new_attrs.items()}
    renamed = {key:by_expression[value] for key,value in old_attrs.items()}
    normalized = re.sub(r'\bbase_typeattr_\d+\b', lambda match: renamed.get(match[0], match[0]), old_product)
    expected_members = {
        'domain': {'sheng_face', 'sheng_touch_app'},
        'file_type': {'sheng_face_data_file', 'sheng_face_exec', 'sheng_face_tmpfs', 'sheng_touch_app_data_file'},
        'exec_type': {'sheng_face_exec'}, 'system_file_type': {'sheng_face_exec'},
        'property_type': {'sheng_face_test_prop'}, 'system_property_type': {'sheng_face_test_prop'},
        'mlstrustedsubject': {'sheng_touch_app'}, 'coredomain': {'sheng_face', 'sheng_touch_app'},
        'halserverdomain': {'sheng_face'}, 'halclientdomain': {'sheng_face'},
    }
    old_lines, new_lines = normalized.splitlines(), new_product.splitlines()
    assert len(old_lines) == len(new_lines)
    seen_members = set()
    for old_line, new_line in zip(old_lines, new_lines):
        if old_line == new_line:
            continue
        old_set = re.fullmatch(r'\(typeattributeset (\w+) \(([\w -]*)\)\)', old_line)
        new_set = re.fullmatch(r'\(typeattributeset (\w+) \(([\w -]*)\)\)', new_line)
        assert old_set and new_set and old_set[1] == new_set[1], (old_line, new_line)
        name = old_set[1]
        old_values, new_values = old_set[2].split(), new_set[2].split()
        added = set(new_values) - set(old_values)
        assert added == expected_members[name]
        assert [value for value in new_values if value not in added] == old_values
        seen_members.add(name)
    assert seen_members == set(expected_members)
    for part in ['odm', 'vendor']:
        print('Staging ' + part, flush=True)
        nodes = {'bin/sheng-touchctl': node('vendor_sheng_touchctl_exec', True),
                 'etc/init/init.sheng.touch.rc': node('vendor_configs_file')} if part == 'vendor' else {}
        outputs[part], trees[part], reports[part] = stage_erofs(
            part, chain[part], entries[part], nodes, work, avb, avbtool)
        assert reports[part]['metadata_preserved']
        assert set(reports[part]['changed_files']) <= set(scope[part])
    # Prevent public/deferred policy inputs from being silently packaged.
    after = work/'system_ext-after'
    for path in (work/'system_ext-before/etc/selinux').rglob('*'):
        rel = path.relative_to(work/'system_ext-before').as_posix()
        if path.is_file() and rel not in scope['system_ext']:
            assert path.read_bytes() == (after/rel).read_bytes(), rel
    assert (after/'etc/selinux/system_ext_sepolicy_and_mapping.sha256').read_bytes() != (
        work/'odm-tree/etc/selinux/precompiled_sepolicy.system_ext_sepolicy_and_mapping.sha256').read_bytes()
    combination = {**chain, **outputs}
    boot_policy = verify_boot_policy(combination, work)
    assert (work/'system-policy/selinux/plat_sepolicy.cil').read_bytes() == (
        PRODUCT/'system/etc/selinux/plat_sepolicy.cil').read_bytes()
    selected = [work/name for name in boot_policy['input_sha256']]
    run([HOST/'secilc', selected[0], '-m', '-M', 'true', '-G', '-c', '30',
         selected[1], '-o', work/'combined-boot-policy-strict', '-f', '/dev/null', *selected[2:]])
    boot_policy['actual_partition_neverallows_passed'] = True
    vintf = verify_vintf(combination, work, args.runtime_vintf)
    for part, algorithm, children in [
        ('vbmeta_system', 'SHA256_RSA2048', ['system_ext', 'product']),
        ('vbmeta', 'SHA256_RSA4096', ['vendor', 'odm'])]:
        outputs[part] = work/(part+'.img')
        merge_parent(avb, avbtool, chain[part], [trees[p] for p in children], outputs[part], algorithm, work)
    complete = work/'complete-chain'
    complete.mkdir()
    for part, path in chain.items():
        (complete/(part+'.img')).symlink_to(outputs.get(part, path).resolve())
    run([HOST/'avbtool', 'verify_image', '--image', complete/'vbmeta.img', '--follow_chain_partitions'])
    assert sha(after/'priv-app/SystemUI/SystemUI.apk') == sha(reference)
    for part in entries:
        validate_inputs(part, entries[part])
    check_sources()
    validate_packaging_inputs(scope, frozen)
    destination = workspace/'artifacts/system-hardware-followup-sheng-r48'
    publish_batch(destination, outputs, dict(revision=48,
        baseline_sha256={part:digests[part] for part in outputs}, entries=entries,
        sources_sha256={name:e['sha256'] for name,e in mirror['inputs'].items()},
        build_log_sha256=sha(args.build_log), post_audit_sha256=sha(args.audit),
        source_mirror_sha256=sha(args.mirror), partition_reports=reports,
        packaging_inputs=frozen, boot_policy=boot_policy, vintf=vintf,
        all_filesystem_stages_verified=True, complete_avb_chain_verified=True,
        original_systemui_unchanged=True, normal_module_build_passed=True,
        full_product_build_passed=False, first_setup_seed_144=True,
        bluetooth_lhdc_software_route=True, usb_standard_rndis=True,
        touch_stock_mode14=True, face_r46_installed=False,
        touch_embedded_jni_sha256=native_sha256,
        matching_product_policy_verified=True,
        product_policy_review=dict(generated_attribute_renames=renamed,
            known_public_member_additions={key:sorted(value) for key,value in expected_members.items()},
            original_rule_statements_unchanged=True),
        touch_report_240_candidate=True, physical_sampling_increase_tested=False,
        hardware_boot_tested=False, work_dir=str(work),
        source_commit=subprocess.check_output(['git','-C',workspace,'rev-parse','HEAD'], text=True).strip()))
    print(destination, flush=True)


if __name__ == '__main__':
    main()
