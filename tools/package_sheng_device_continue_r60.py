#!/usr/bin/env python3
"""Seal the QTI, tap-capability and wakeup-label batch over installed Android r53."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from package_sheng_batch_helpers import (
    certificates, debugfs, erofs_input_keys, merge_parent, packaging_input_path,
    publish_batch, stage_erofs, validate_inputs, validate_packaging_inputs,
    verify_boot_policy,
)
from package_sheng_model_followup import HOST, PRODUCT, ROM, parse_image, sha
from package_sheng_overlay_followup import public_key

UI_HASH = '33017b0d59e28da5db3e089a98f49601de508228a012392ee2d04c82cda3ccb1'
TAP_KEYS = {'ro.vendor.sensors.xiaomi.single_tap', 'ro.vendor.sensors.xiaomi.double_tap'}
TAP_RESOURCES = {'config_dozeTapSensorType', 'config_dozeDoubleTapSensorType'}
WAKEUP_PATHS = {
    '/devices/platform/soc/soc:xm_battmngr/wakeup',
    '/devices/platform/soc/soc:fingerprint_fpc/wakeup',
    '/devices/platform/soc/soc:xiaomi_wifi_gpio/wakeup',
    '/devices/platform/soc/8c0000.qcom,qupv3_2_geni_se/884000.i2c/i2c-5/5-004c/wakeup',
}


def properties(path):
    result = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            result.setdefault(key, []).append(value)
    return result


def resources(dump):
    result = {}
    # Keep configurations, values and resource identities from aapt2; only the
    # named resource blocks may differ between the installed and rebuilt APK.
    for block in re.split(r'(?m)(?=^\s+resource 0x[0-9a-f]+ )', dump)[1:]:
        header = block.splitlines()[0]
        match = re.search(r'resource 0x[0-9a-f]+ (\S+)', header)
        assert match, header
        assert match[1] not in result
        result[match[1]] = block.strip()
    assert result, 'Unrecognized aapt2 resource dump'
    return result


def split_policy_selection(work):
    """Ensure init cannot select an unchanged precompiled policy for this delta."""
    roots = {
        'system': work / 'system-policy/selinux',
        'system_ext': work / 'system_ext-after/etc/selinux',
        'product': work / 'product-policy/selinux',
    }
    candidates = [work / (p + '-tree/etc/selinux/precompiled_sepolicy')
                  for p in ['odm', 'vendor']]
    precompiled = next((p for p in candidates if p.is_file()), None)
    if precompiled is None:
        return {'split_policy_selected_by_partition_hashes': True,
                'precompiled_policy': None, 'hash_mismatches': []}
    mismatches = []
    for part, root in roots.items():
        suffix = part + '_sepolicy_and_mapping.sha256'
        actual, cached = root / suffix, precompiled.with_name(precompiled.name + '.' + suffix)
        if not actual.exists() and not cached.exists():
            continue
        if not actual.is_file() or not cached.is_file():
            mismatches.append(suffix)
            continue
        actual_id, cached_id = actual.read_text().splitlines(), cached.read_text().splitlines()
        if not actual_id or not actual_id[0] or actual_id[:1] != cached_id[:1]:
            mismatches.append(suffix)
    assert mismatches, 'init would load an unchanged precompiled policy instead of the r60 CIL'
    return {'split_policy_selected_by_partition_hashes': True,
            'precompiled_policy': str(precompiled.relative_to(work)),
            'hash_mismatches': mismatches}


def current_recovery_root(avb, avbtool, base, recovery, work):
    """Align the AVB hash with the independently installed r59 dependency."""
    footer, header, descriptors, _ = parse_image(avb, avbtool, base)
    assert footer is None and header.algorithm_type == 2 and not header.public_key_metadata_size
    updated = copy.deepcopy(descriptors)
    selected = [d for d in updated if isinstance(d, avbtool.AvbHashDescriptor)
                and d.partition_name == 'recovery']
    assert len(selected) == 1
    descriptor = selected[0]
    with recovery.open('rb') as stream:
        current = hashlib.new(descriptor.hash_algorithm,
                              descriptor.salt + stream.read(descriptor.image_size)).digest()
    if current == descriptor.digest:
        return base, False
    descriptor.image_size = recovery.stat().st_size
    descriptor.digest = hashlib.new(descriptor.hash_algorithm,
                                   descriptor.salt + recovery.read_bytes()).digest()
    blob = avb._generate_vbmeta_blob(
        algorithm_name='SHA256_RSA4096',
        key_path=str(ROM / 'external/avb/test/data/testkey_rsa4096.pem'),
        public_key_metadata_path=None, descriptors=updated,
        chain_partitions_use_ab=None, chain_partitions_do_not_use_ab=None,
        rollback_index=header.rollback_index, flags=header.flags,
        rollback_index_location=header.rollback_index_location,
        props=None, props_from_file=None, kernel_cmdlines=None,
        setup_rootfs_from_kernel=None, ht_desc_to_setup=None,
        include_descriptors_from_image=None, signing_helper=None,
        signing_helper_with_files=None, release_string=header.release_string,
        append_to_release_string=None,
        required_libavb_version_minor=header.required_libavb_version_minor)
    assert len(blob) <= base.stat().st_size
    target = work / 'vbmeta-current-recovery.img'
    with target.open('xb') as stream:
        stream.write(blob + bytes(base.stat().st_size - len(blob)))
    _, new_header, new_descriptors, _ = parse_image(avb, avbtool, target)
    assert avbtool.verify_vbmeta_signature(new_header, blob)
    assert public_key(base, footer, header) == public_key(target, None, new_header)
    for field in ('flags', 'rollback_index', 'rollback_index_location', 'algorithm_type',
                  'required_libavb_version_major', 'required_libavb_version_minor', 'release_string'):
        assert getattr(header, field) == getattr(new_header, field), field
    assert len(descriptors) == len(new_descriptors)
    delta = [(a, b) for a, b in zip(descriptors, new_descriptors) if a.encode() != b.encode()]
    assert len(delta) == 1 and delta[0][0].partition_name == 'recovery'
    assert delta[0][1].encode() == descriptor.encode()
    return target, True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'build-log', 'audit', 'mirror', 'work']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--factory-receipt', type=Path)
    parser.add_argument('--configuration-only', action='store_true',
                        help='Package r61 tap/wakeup configuration; retain installed QTI service')
    args = parser.parse_args()
    revision = 61 if args.configuration_only else 60
    workspace = args.workspace.resolve(strict=True)
    work = args.work
    work.mkdir(exist_ok=False)
    assert shutil.disk_usage(work).free > 6 * 1024**3
    assert '#### build completed successfully' in args.build_log.read_text()
    assert (HOST / 'soong_build').read_bytes()[:4] == b'\x7fELF'
    audit, mirror = [json.loads(p.read_text()) for p in [args.audit, args.mirror]]
    factory = None
    assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
    assert datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(audit['date_utc']).timestamp() < 7200
    assert mirror['passed']
    required_sources = {
        'interfaces/compat/codec2/Android.bp',
        'interfaces/compat/codec2/qti_service.cpp',
        'properties/vendor.prop',
        'overlay/FrameworkResOverlaySheng/res/values/platform-defaults.xml',
        'rootdir/etc/init.sm8550.rc',
        'sepolicy/vendor/genfs_contexts',
    }
    assert {'device/xiaomi/sheng/' + name for name in required_sources} <= set(mirror['inputs']), \
        'Source mirror omits an r60 build input'
    if not args.configuration_only:
        assert args.factory_receipt is not None
        factory = json.loads(args.factory_receipt.read_text())
        assert factory['returncode'] == 0 and factory['registered_service'] is False
        assert factory['serial'] == 'ca10ede3' and factory['listed_components'] > 0
        assert factory['seccomp_enabled'] is True and factory['process_teardown_passed'] is True

    def sources():
        for name, entry in mirror['inputs'].items():
            assert entry['kind'] == 'file'
            assert sha(workspace / name) == sha(ROM / name) == entry['sha256'], name
        postprocessor = 'device/xiaomi/sheng/tools/postprocess_vendor.py'
        assert sha(workspace / postprocessor) == sha(ROM / postprocessor), postprocessor

    sources()
    packaging_inputs = {
        name: sha(packaging_input_path(name))
        for name in set().union(*(erofs_input_keys(p) for p in ['vendor', 'odm']))
    }
    validate_packaging_inputs(['vendor', 'odm'], packaging_inputs)
    previous = json.loads((workspace / 'artifacts/system-hardware-followup-sheng-r53/build-result.json').read_text())
    assert previous['complete_avb_chain_verified'] and previous['original_systemui_unchanged']
    files = previous['files'] + previous['unchanged_partition_files']
    digests = {e['partition']: e['sha256'] for e in files}
    cache = Path(previous['work_dir']) / 'complete-chain'
    chain = {p.stem: p for p in cache.glob('*.img')}
    assert all(sha(chain[p]) == digest for p, digest in digests.items())
    for dependency in previous['unchanged_boot_dependencies']:
        if dependency['partition'] != 'recovery':
            path = chain[dependency['partition']]
            assert path.stat().st_size == dependency['bytes'] and sha(path) == dependency['sha256']
    restore = json.loads((workspace / 'reports/device/r38-restore-20261110/restore-manifest.json').read_text())
    system = next(entry for entry in restore['files'] if entry['partition'] == 'system')
    assert chain['system'].stat().st_size == system['bytes'] and sha(chain['system']) == system['sha256']
    # Recovery was updated independently after Android r53. Verify the actual
    # current dependency, keeping it out of this Android flashing batch.
    recovery = json.loads((workspace / 'reports/device/20261112-recovery-pen/r59-package.json').read_text())
    assert recovery['revision'] == 59 and recovery['avb_verified']
    chain['recovery'] = Path(recovery['image'])
    assert sha(chain['recovery']) == recovery['sha256']
    commands = []

    def run(argv):
        value = subprocess.run(list(map(str, argv)), text=True, capture_output=True)
        commands.append(dict(argv=list(map(str, argv)), returncode=value.returncode,
                             stdout=value.stdout, stderr=value.stderr))
        (work / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        assert value.returncode == 0, value.stdout + value.stderr
        return value.stdout

    base_ext = work / 'system_ext-after'
    base_ext.mkdir()
    debugfs(chain['system_ext'], f'rdump / {base_ext}')
    ref = base_ext / 'priv-app/SystemUI/SystemUI.apk'
    assert sha(ref) == UI_HASH
    for part in ['vendor', 'odm']:
        run([HOST / 'fsck.erofs', '-d0', '--extract=' + str(work / ('baseline-' + part)),
             '--preserve', chain[part]])
    before = work / 'baseline-vendor'
    prop = PRODUCT / 'vendor/build.prop'
    old, new = properties(before / 'build.prop'), properties(prop)
    assert old.keys() == new.keys()
    changed = {key for key in old if old[key] != new[key]}
    assert TAP_KEYS <= changed <= TAP_KEYS | {'ro.vendor.build.uuid'}, changed
    assert all(old[key] == ['true'] and new[key] == ['false'] for key in TAP_KEYS)
    assert old['audio.deep_buffer.media'] == new['audio.deep_buffer.media'] == ['true']

    init = PRODUCT / 'vendor/etc/init/init.sm8550.rc'
    old_init = (before / 'etc/init/init.sm8550.rc').read_text().splitlines()
    new_init = init.read_text().splitlines()
    removed = [line for line in old_init if line not in new_init]
    assert len(removed) == 6 and all('/gesture_' in line for line in removed)
    assert [line for line in old_init if line not in removed] == new_init
    old_policy = set((before / 'etc/selinux/vendor_sepolicy.cil').read_text().splitlines())
    new_policy = set((PRODUCT / 'vendor/etc/selinux/vendor_sepolicy.cil').read_text().splitlines())
    assert old_policy <= new_policy, 'Policy removals outside batch'
    added = new_policy - old_policy
    assert len(added) == 4 and all(line.startswith('(genfscon sysfs ') for line in added), added
    assert all(any(path in line for path in WAKEUP_PATHS) and 'sysfs_wakeup' in line for line in added)
    assert all(any(path in line for line in added) for path in WAKEUP_PATHS)
    (work / 'policy-delta.json').write_text(json.dumps(sorted(added), indent=2) + '\n')

    apk = PRODUCT / 'odm/overlay/FrameworkResOverlaySheng.apk'
    run([HOST / 'apksigner', 'verify', apk])
    run([HOST / 'zipalign', '-c', '-P', '16', '4', apk])
    baseline_apk = work / 'baseline-odm/overlay/FrameworkResOverlaySheng.apk'
    assert certificates(apk) == certificates(baseline_apk)
    old_resources, new_resources = [resources(run([HOST / 'aapt2', 'dump', 'resources', p]))
                                    for p in [baseline_apk, apk]]
    assert old_resources.keys() == new_resources.keys()
    resource_delta = {name.rsplit('/', 1)[-1] for name in old_resources
                      if old_resources[name] != new_resources[name]}
    assert resource_delta == TAP_RESOURCES, resource_delta

    scope = {'vendor': ['build.prop',
                        'etc/init/init.sm8550.rc', 'etc/selinux/vendor_sepolicy.cil'],
             'odm': ['overlay/FrameworkResOverlaySheng.apk']}
    if not args.configuration_only:
        qti = PRODUCT / 'vendor/bin/hw/vendor.qti.media.c2@1.0-service'
        assert qti.is_file() and qti.read_bytes()[:4] == b'\x7fELF'
        assert b'ShengQtiCodec2' in qti.read_bytes()
        assert sha(qti) != sha(before / 'bin/hw/vendor.qti.media.c2@1.0-service')
        dynamic = run(['/usr/bin/readelf', '-d', qti])
        assert 'libavservices_minijail.so' in dynamic and 'libcodec2_hidl@1.0.so' in dynamic
        assert factory['service_sha256'] == sha(qti)
        scope['vendor'].insert(0, 'bin/hw/vendor.qti.media.c2@1.0-service')
    entries = {p: {name: dict(source=str(PRODUCT / p / name), kind='file',
                              bytes=(PRODUCT / p / name).stat().st_size, sha256=sha(PRODUCT / p / name))
                   for name in names} for p, names in scope.items()}
    for p, values in entries.items():
        validate_inputs(p, values)
    sys.path.insert(0, str(ROM / 'external/avb'))
    import avbtool
    avb = avbtool.Avb()
    outputs, trees, stages = {}, {}, {}
    for p in ['vendor', 'odm']:
        outputs[p], trees[p], stages[p] = stage_erofs(p, chain[p], entries[p], {}, work, avb, avbtool)
        assert stages[p]['metadata_preserved']
        assert set(stages[p]['changed_files']) == set(scope[p])
    if args.configuration_only:
        retained_qti = 'bin/hw/vendor.qti.media.c2@1.0-service'
        assert sha(work / 'vendor-tree' / retained_qti) == sha(before / retained_qti)
    boot_policy = verify_boot_policy({**chain, **outputs}, work)
    boot_policy.update(split_policy_selection(work))
    outputs['vbmeta'] = work / 'vbmeta.img'
    current_root, recovery_descriptor_updated = current_recovery_root(
        avb, avbtool, chain['vbmeta'], chain['recovery'], work)
    merge_parent(avb, avbtool, current_root, [trees['vendor'], trees['odm']],
                 outputs['vbmeta'], 'SHA256_RSA4096', work)
    complete = work / 'complete-chain'
    complete.mkdir()
    for part, path in chain.items():
        (complete / (part + '.img')).symlink_to(outputs.get(part, path).resolve())
    run([HOST / 'avbtool', 'verify_image', '--image', complete / 'vbmeta.img', '--follow_chain_partitions'])
    sources()
    validate_packaging_inputs(['vendor', 'odm'], packaging_inputs)
    for p, values in entries.items():
        validate_inputs(p, values)
    unchanged = [dict(partition=p, name=p + '.img', bytes=chain[p].stat().st_size, sha256=digests[p])
                 for p in digests if p not in outputs]
    publish_batch(workspace / f'artifacts/system-hardware-followup-sheng-r{revision}', outputs, dict(
        revision=revision, baseline_revision=53, baseline_sha256=digests,
        unchanged_partition_files=unchanged, entries=entries, partition_reports=stages,
        unchanged_boot_dependencies=[dict(partition=p, bytes=path.stat().st_size, sha256=sha(path))
                                    for p, path in chain.items() if p not in digests],
        original_systemui_unchanged=True, complete_avb_chain_verified=True,
        all_filesystem_stages_verified=True, normal_module_build_passed=True,
        full_product_build_passed=False, hardware_boot_tested=False, boot_policy=boot_policy,
        qti_source_service_integrated=not args.configuration_only,
        installed_qti_retained=args.configuration_only,
        retained_qti_sha256=sha(before / 'bin/hw/vendor.qti.media.c2@1.0-service'),
        nonexistent_tap_sensors_removed=True,
        precise_wakeup_labels_integrated=True, no_new_allow_rules=True,
        touch_r50_retained=True, dolby_ui_r51_retained=True, dolby_media_r52_retained=True,
        keyboard_r53_retained=True, pen_fixed=False, face_candidate_installed=False,
        recovery_revision_retained=59, recovery_hash_descriptor_updated=recovery_descriptor_updated,
        vintf_unchanged=True, factory_probe=factory, changed_properties=sorted(changed),
        changed_overlay_resources=sorted(resource_delta), policy_added=sorted(added),
        sources_sha256={n: e['sha256'] for n, e in mirror['inputs'].items()},
        generated_vendor_postprocessor_sha256=sha(workspace / 'device/xiaomi/sheng/tools/postprocess_vendor.py'),
        packaging_inputs_sha256=packaging_inputs,
        build_log_sha256=sha(args.build_log), source_mirror_sha256=sha(args.mirror),
        post_audit_sha256=sha(args.audit), work_dir=str(work),
        source_commit=subprocess.check_output(['git', '-C', workspace, 'rev-parse', 'HEAD'], text=True).strip()))
    print(f'Published device continuation r{revision}', flush=True)


if __name__ == '__main__':
    main()
