#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Package qualified frozen stylus artifacts over the sealed r64 partition chain."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import xml.etree.ElementTree as ET

from package_sheng_batch_helpers import (
    certificates, complete_metadata, debugfs, erofs_input_keys, merge_parent,
    packaging_input_path, publish_batch, run, sha, stage_erofs, stage_ext4,
    validate_inputs, validate_packaging_inputs, verify_boot_policy, verify_vintf,
)
from package_sheng_device_continue_r60 import split_policy_selection, UI_HASH
from package_sheng_model_followup import HOST, PRODUCT, ROM
from sheng_stylus_evidence import source_hashes_for_guard, qualified_build_record

APP = 'priv-app/ShengStylus/ShengStylus.apk'
SERVICE = 'bin/hw/vendor.lineage.sheng.stylus-service'
LIBRARY = 'lib64/vendor.lineage.sheng.stylus-V1-ndk.so'
RC = 'etc/init/vendor.lineage.sheng.stylus-service.rc'
MANIFEST = 'etc/vintf/manifest/vendor.lineage.sheng.stylus-service.xml'
PERMISSION = 'etc/permissions/privapp-permissions-org.lineageos.sheng.stylus.xml'
MATRIX = 'etc/vintf/compatibility_matrix.device.xml'
PARTITIONS = {'system', 'system_ext', 'product', 'vendor', 'odm', 'vendor_dlkm',
              'system_dlkm', 'boot', 'init_boot', 'vendor_boot', 'dtbo', 'recovery',
              'vbmeta', 'vbmeta_system'}


def main():
    global PRODUCT
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('workspace', 'guard', 'artifacts', 'runtime-inputs', 'work'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--discard-verified-before-trees', action='store_true',
                        help='Release redundant new scratch trees after each ext4 stage passes; retain sealed images')
    args = parser.parse_args()
    workspace = args.workspace.resolve(strict=True)
    guard = qualified_build_record(args.guard, workspace, ROM)
    PRODUCT = Path(guard['product_root'])
    verified = json.loads(args.artifacts.read_text())
    assert guard['qualified_module_build_passed'] and guard['compiler_restored']
    assert (guard['swap_policy']['complete'] and guard['swap_policy']['policy'] == 'C-only'
            and guard['swap_policy']['e_drive_swap_allowed'] is False)
    assert verified['passed'] and verified['api_frozen'] and verified['qualified_module_build_passed']
    assert verified['targeted_module_build_passed'] == guard['targeted_module_build_passed']
    assert verified['frozen_api_version'] == 1 and verified['guard_sha256'] == sha(args.guard)
    assert verified['source_sync_sha256'] == sha(args.guard.parent/'stylus-source-sync.json')
    runtime_root = args.runtime_inputs.resolve(strict=True)
    runtime_receipt = runtime_root/'receipt.json'
    runtime_receipt_hash = sha(runtime_receipt)
    runtime_receipt_relative = runtime_receipt.relative_to(workspace).as_posix()
    runtime = json.loads(runtime_receipt.read_text())
    assert runtime['passed'] and runtime['baseline_vintf_compatible']
    assert runtime['serial'] == 'ca10ede3' and not runtime['device_changed']
    assert runtime['before'] == runtime['after']
    assert runtime['before']['slot'] == '_a' and runtime['before']['selinux'] == 'Enforcing'
    assert runtime['before']['kernel'] == '5.15.220-gf9ca2b71f672'
    runtime_hashes = dict(runtime['inputs'])

    def check_runtime_inputs():
        assert sha(runtime_receipt) == runtime_receipt_hash
        assert sha(runtime_root/'kernel.config') == runtime['kernel_config_sha256']
        for remote, digest in runtime_hashes.items():
            relative = 'kernel.config.gz' if remote == '/proc/config.gz' else remote.removeprefix('/')
            cached = (runtime_root/relative).resolve(strict=True)
            assert cached.is_relative_to(runtime_root) and sha(cached) == digest

    check_runtime_inputs()
    assert (HOST/'soong_build').read_bytes()[:4] == b'\x7fELF'
    assert sha(PRODUCT/'system_ext'/APP) == verified['apk_sha256']
    assert sha(PRODUCT/'vendor'/SERVICE) == verified['service_sha256']
    assert sha(PRODUCT/'vendor'/LIBRARY) == verified['dependency_sha256'][Path(LIBRARY).name]
    for relative, digest in verified['policy_sha256'].items(): assert sha(PRODUCT/relative) == digest
    assert sha(PRODUCT/'system'/MATRIX) == verified['framework_matrix_sha256']
    assert sha(PRODUCT/'vendor'/MANIFEST) == verified['vintf_fragment_sha256']
    assert sha(PRODUCT/'vendor'/RC) == verified['init_rc_sha256']
    assert sha(PRODUCT/'system_ext'/PERMISSION) == verified['privileged_permissions_sha256']
    sources = source_hashes_for_guard(workspace, ROM, args.guard)
    assert sources == verified['source_sha256']

    def check_sources():
        assert sources == source_hashes_for_guard(workspace, ROM, args.guard)
        assert verified['source_sync_sha256'] == sha(args.guard.parent/'stylus-source-sync.json')

    check_sources()
    previous_path = workspace/'artifacts/system-hardware-followup-sheng-r64/build-result.json'
    previous = json.loads(previous_path.read_text())
    assert previous['revision'] == 64 and previous['complete_avb_chain_verified']
    assert previous['original_systemui_unchanged'] and previous['installed_qti_retained']
    baseline = [dict(entry, name=entry['partition']+'.img') for entry in
                previous['files']+previous['unchanged_partition_files']+previous['unchanged_boot_dependencies']]
    assert len(baseline) == 14 and {entry['partition'] for entry in baseline} == PARTITIONS
    cache = Path(previous['work_dir'])/'complete-chain'
    chain = {entry['partition']: cache/entry['name'] for entry in baseline}
    for entry in baseline:
        path = chain[entry['partition']]
        assert path.stat().st_size == entry['bytes'] and sha(path) == entry['sha256'], path
    assert sha(PRODUCT/'vendor/bin/hw/vendor.qti.media.c2@1.0-service') == previous['retained_qti_sha256']
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    assert work.stat().st_dev == Path('/').stat().st_dev, 'Use the native C-backed Linux filesystem for partition metadata'
    assert shutil.disk_usage(work).free > 20*1024**3, 'Native partition staging requires at least 20 GiB free'
    reference = work/'original-SystemUI.apk'
    debugfs(chain['system_ext'], 'dump /priv-app/SystemUI/SystemUI.apk '+str(reference))
    assert sha(reference) == UI_HASH
    assert certificates(PRODUCT/'system_ext'/APP) == certificates(reference)
    entries = {part: {} for part in ('system', 'system_ext', 'vendor', 'product')}

    def add(part, relative):
        path = PRODUCT/part/relative
        assert path.is_file() and not path.is_symlink()
        entries[part][relative] = dict(source=str(path), kind='file', bytes=path.stat().st_size, sha256=sha(path))

    add('system', MATRIX)
    for relative in (APP, PERMISSION): add('system_ext', relative)
    for relative in (SERVICE, LIBRARY, RC, MANIFEST): add('vendor', relative)
    for part in ('system_ext', 'vendor', 'product'):
        for path in sorted((PRODUCT/part/'etc/selinux').rglob('*')):
            if path.is_file(): add(part, str(path.relative_to(PRODUCT/part)))
    build_inputs = {name: sha(packaging_input_path(name)) for name in erofs_input_keys('vendor')}
    validate_packaging_inputs(entries, build_inputs)
    # The retained global concat predates this newly installed executable.
    # Add only its source-verified device labels and retain every baseline rule.
    contexts_source = workspace/'device/xiaomi/sheng/interfaces/input/stylus/sepolicy/vendor/file_contexts'
    baseline_contexts = packaging_input_path('@sepolicy_file_contexts').read_text()
    context_rules = {line.split()[0]: line.split()[1:] for line in baseline_contexts.splitlines()
                     if line.strip() and not line.lstrip().startswith('#')}
    extra_lines = []
    for line in contexts_source.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'): continue
        key, *values = line.split()
        if key in context_rules: assert context_rules[key] == values
        else: extra_lines.append(line)
    scoped_contexts = work/'stylus-file-contexts.txt'
    scoped_contexts.write_text(baseline_contexts.rstrip()+'\n'+'\n'.join(extra_lines)+'\n')
    scoped_contexts_sha256 = sha(scoped_contexts)
    run([HOST/'checkfc', PRODUCT/verified['precompiled_policy_path'], scoped_contexts])
    frozen_inputs = {part: {name: entry['sha256'] for name, entry in values.items()} for part, values in entries.items()}
    sys.path.insert(0, str(ROM/'external/avb'))
    import avbtool
    avb = avbtool.Avb()
    outputs, descriptors, stages = {}, {}, {}
    discarded_before_trees = []
    timestamp = 1230768000*10**9

    def metadata(part, name, directory):
        label = ('vendor_sheng_stylus_exec' if name == SERVICE else
                 'vendor_file' if name.startswith('lib64/') else 'vendor_configs_file') if part == 'vendor' else 'system_file'
        return dict(uid=0, gid=0, mode=0o755 if directory or name == SERVICE else 0o644,
                    mtime_ns=timestamp, selinux='u:object_r:'+label+':s0')

    for part in ('system', 'system_ext', 'product', 'vendor'):
        assert shutil.disk_usage('/mnt/c').free >= 6*1024**3, 'C: staging space fell below the retained reserve'
        validate_inputs(part, entries[part], source_product=PRODUCT)
        nodes = {}
        if part == 'vendor':
            old_nodes, _ = complete_metadata(chain[part])
            exists = lambda name: '/'+name in old_nodes
        else:
            prefix = '/system' if part == 'system' else ''
            present = {}
            def exists(name):
                if name not in present:
                    path = prefix+'/'+name
                    try:
                        present[name] = bool(re.search(r'Inode:\s*\d+', debugfs(chain[part], 'stat '+path)))
                    except RuntimeError as error:
                        if path+': File not found by ext2_lookup' not in str(error):
                            raise
                        present[name] = False
                return present[name]
        for relative in entries[part]:
            if not exists(relative): nodes[relative] = metadata(part, relative, False)
            for parent in PurePosixPath(relative).parents:
                if str(parent) == '.': break
                if exists(str(parent)): break
                nodes[str(parent)] = metadata(part, str(parent), True)
        print('Staging '+part+' with '+str(len(entries[part]))+' declared files', flush=True)
        if part == 'vendor':
            outputs[part], descriptors[part], stages[part] = stage_erofs(part, chain[part], entries[part], nodes, work, avb, avbtool, source_product=PRODUCT, file_contexts=scoped_contexts)
        else:
            outputs[part], descriptors[part], stages[part] = stage_ext4(part, chain[part], entries[part], nodes,
                work, avb, avbtool, certificates(reference), source_product=PRODUCT)
            if args.discard_verified_before_trees:
                # The sealed r64 source image and verified r65 output retain
                # both filesystem states. Only this new run's redundant dump
                # is released, after all content/inode/AVB stage checks pass.
                before = work/(part+'-before')
                assert not before.is_symlink() and before.resolve(strict=True).parent == work
                assert before.is_dir() and shutil.rmtree.avoids_symlink_attacks
                (work/(part+'-stage.json')).write_text(json.dumps(dict(
                    partition=part, passed=True, baseline_sha256=sha(chain[part]),
                    output_sha256=sha(outputs[part]), verification=stages[part]), indent=2)+'\n')
                shutil.rmtree(before)
                discarded_before_trees.append(part)
    assert sha(work/'system_ext-after/priv-app/SystemUI/SystemUI.apk') == UI_HASH
    assert sha(work/'vendor-tree/bin/hw/vendor.qti.media.c2@1.0-service') == previous['retained_qti_sha256']
    # Resolve the direct libraries from the actual mixed partition images.
    # The normally built daemon must not rely on an uninstalled out/ library.
    providers = {}
    for name, digest in verified['dependency_sha256'].items():
        assert re.fullmatch(r'[A-Za-z0-9_.+-]+\.so', name), name
        candidates = [('vendor', work/'vendor-tree/lib64'/name),
                      ('system', work/'system-after/system/lib64'/name)]
        matches = [(part, path) for part, path in candidates if path.is_file()]
        assert matches, 'No installed direct library provider: '+name
        part, path = matches[0]
        assert sha(path) == digest, 'Installed direct library differs from the normal build: '+name
        providers[name] = dict(partition=part, relative='lib64/'+name, sha256=digest)
    assert Path(LIBRARY).name in providers
    run([HOST/'fsck.erofs', '-d0', '--extract='+str(work/'odm-tree'), '--preserve', chain['odm']])
    mixed = dict(chain, **outputs)
    boot_policy = verify_boot_policy(mixed, work)
    boot_policy.update(split_policy_selection(work))
    vintf = verify_vintf(mixed, work, args.runtime_inputs)
    installed = ET.parse(work/'vendor-tree'/MANIFEST).getroot()
    assert installed.findtext('hal/name') == 'vendor.lineage.sheng.stylus'
    assert installed.findtext('hal/version') == '1'
    outputs['vbmeta_system'] = work/'vbmeta_system.img'
    outputs['vbmeta'] = work/'vbmeta.img'
    merge_parent(avb, avbtool, chain['vbmeta_system'], [descriptors[p] for p in ('system', 'system_ext', 'product')],
                 outputs['vbmeta_system'], 'SHA256_RSA2048', work)
    merge_parent(avb, avbtool, chain['vbmeta'], [descriptors['vendor']], outputs['vbmeta'], 'SHA256_RSA4096', work)
    complete = work/'complete-chain'
    complete.mkdir()
    for part, path in chain.items(): (complete/(part+'.img')).symlink_to(outputs.get(part, path).resolve())
    run([HOST/'avbtool', 'verify_image', '--image', complete/'vbmeta.img', '--follow_chain_partitions'])
    check_sources()
    validate_packaging_inputs(entries, build_inputs)
    assert sha(scoped_contexts) == scoped_contexts_sha256
    check_runtime_inputs()
    for part, files in frozen_inputs.items():
        assert all(sha(PRODUCT/part/name) == digest for name, digest in files.items())
    report = dict(revision=65, baseline_revision=64, baseline_partitions=baseline,
        baseline_manifest_sha256=sha(previous_path), entries=entries, partition_reports=stages,
        unchanged_partition_files=[entry for entry in baseline if entry['partition'] not in outputs],
        unchanged_boot_dependencies=[], work_dir=str(work),
        normal_module_build_passed=guard['normal_module_build_passed'],
        qualified_module_build_passed=True, targeted_module_build_passed=guard['targeted_module_build_passed'],
        frozen_api_version=1, frozen_api_hash=verified['frozen_api_hash'],
        build_swap_policy='C-only', e_drive_swap_allowed=False,
        native_c_staging=True, discarded_verified_before_trees=discarded_before_trees,
        stylus_artifacts_sha256=sha(args.artifacts), guard_sha256=sha(args.guard),
        stylus_artifact_receipt=args.artifacts.resolve(strict=True).relative_to(workspace).as_posix(),
        guard_receipt=args.guard.resolve(strict=True).relative_to(workspace).as_posix(),
        native_dependency_providers=providers,
        runtime_inputs_verified=True, runtime_inputs_receipt=runtime_receipt_relative,
        runtime_inputs_receipt_sha256=runtime_receipt_hash,
        sources_sha256=sources, packaging_inputs_sha256=build_inputs,
        scoped_file_contexts_sha256=scoped_contexts_sha256,
        all_filesystem_stages_verified=True, complete_avb_chain_verified=True,
        original_systemui_unchanged=True, installed_qti_retained=True,
        retained_qti_sha256=previous['retained_qti_sha256'], face_candidate_installed=False,
        keyboard_r53_retained=True, recovery_revision_retained=59,
        fingerprint_control_label_corrected=True, pen_settings_preinstalled=True,
        pen_permanent_service_preinstalled=True, pen_permanent_service_hardware_tested=False,
        native_crash_auto_recovery_passed=False, full_product_build_passed=False,
        boot_policy=boot_policy, vintf=vintf, hardware_boot_tested=False)
    publish_batch(workspace/'artifacts/system-hardware-followup-sheng-r65', outputs, report)
    print('Published sealed r65 stylus candidate; device installation remains pending')


if __name__ == '__main__': main()
