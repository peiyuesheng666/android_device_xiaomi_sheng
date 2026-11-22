#!/usr/bin/env python3
"""Seal the single FPC control-label correction over installed r61."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys

from package_sheng_batch_helpers import (
    debugfs, erofs_input_keys, merge_parent, packaging_input_path, publish_batch,
    stage_erofs, validate_inputs, validate_packaging_inputs, verify_boot_policy,
)
from package_sheng_device_continue_r60 import split_policy_selection
from package_sheng_model_followup import HOST, PRODUCT, ROM, sha

CONTROL_PATH = '/devices/platform/soc/soc:fingerprint_fpc/wakeup_enable'
CONTROL_RULE = (f'(genfscon sysfs "{CONTROL_PATH}" '
                '(u object_r sysfs_fingerprint_sheng ((s0) (s0))))')
POLICY_PATH = 'etc/selinux/vendor_sepolicy.cil'
SOURCE_PATH = 'device/xiaomi/sheng/sepolicy/vendor/genfs_contexts'


def validate_policy_delta(old, new):
    before, after = old.splitlines(), new.splitlines()
    assert CONTROL_RULE not in before, 'Baseline is already corrected'
    assert after.count(CONTROL_RULE) == 1, 'Missing or duplicate exact control rule'
    assert [line for line in after if line != CONTROL_RULE] == before, \
        'Only the exact control genfscon may change; ordering and existing policy must remain'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'build-log', 'audit', 'mirror', 'work']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--genfs-probe', type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve(strict=True)
    work = args.work.resolve()
    work.mkdir(exist_ok=False)
    assert shutil.disk_usage(work).free > 6 * 1024**3
    assert '#### build completed successfully' in args.build_log.read_text()
    assert (HOST / 'soong_build').read_bytes()[:4] == b'\x7fELF'
    audit, mirror = [json.loads(path.read_text()) for path in [args.audit, args.mirror]]
    assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
    assert datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(audit['date_utc']).timestamp() < 7200
    assert mirror['passed'] and set(mirror['inputs']) == {SOURCE_PATH}

    def sources():
        assert sha(workspace / SOURCE_PATH) == sha(ROM / SOURCE_PATH) == mirror['inputs'][SOURCE_PATH]['sha256']

    sources()
    frozen = {name: sha(packaging_input_path(name)) for name in erofs_input_keys('vendor')}
    validate_packaging_inputs(['vendor'], frozen)
    previous_path = workspace / 'artifacts/system-hardware-followup-sheng-r61/build-result.json'
    previous = json.loads(previous_path.read_text())
    assert previous['revision'] == 61 and previous['complete_avb_chain_verified']
    assert previous['installed_qti_retained'] and previous['original_systemui_unchanged']
    baseline = [dict(entry, name=entry['partition'] + '.img') for entry in
                (previous['files'] + previous['unchanged_partition_files'] +
                 previous['unchanged_boot_dependencies'])]
    assert len(baseline) == len({entry['partition'] for entry in baseline}) == 14
    cache = Path(previous['work_dir']) / 'complete-chain'
    chain = {entry['partition']: cache / (entry['partition'] + '.img') for entry in baseline}
    for entry in baseline:
        path = chain[entry['partition']]
        assert path.stat().st_size == entry['bytes'] and sha(path) == entry['sha256'], path
    commands = []

    def run(argv):
        result = subprocess.run(list(map(str, argv)), text=True, capture_output=True)
        commands.append(dict(argv=list(map(str, argv)), returncode=result.returncode,
                             stdout=result.stdout, stderr=result.stderr))
        (work / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    before = work / 'baseline-vendor'
    run([HOST / 'fsck.erofs', '-d0', '--extract=' + str(before), '--preserve', chain['vendor']])
    policy = PRODUCT / 'vendor' / POLICY_PATH
    validate_policy_delta((before / POLICY_PATH).read_text(), policy.read_text())
    qti = 'bin/hw/vendor.qti.media.c2@1.0-service'
    assert sha(before / qti) == previous['retained_qti_sha256']
    entry = dict(source=str(policy), kind='file', bytes=policy.stat().st_size, sha256=sha(policy))
    entries = {POLICY_PATH: entry}
    validate_inputs('vendor', entries)
    sys.path.insert(0, str(ROM / 'external/avb'))
    import avbtool
    avb = avbtool.Avb()
    vendor, tree, stage = stage_erofs('vendor', chain['vendor'], entries, {}, work, avb, avbtool)
    assert stage['metadata_preserved'] and stage['changed_files'] == [POLICY_PATH]
    assert sha(work / 'vendor-tree' / qti) == previous['retained_qti_sha256']
    validate_policy_delta((before / POLICY_PATH).read_text(),
                          (work / 'vendor-tree' / POLICY_PATH).read_text())
    ext = work / 'system_ext-after'
    ext.mkdir()
    debugfs(chain['system_ext'], f'rdump / {ext}')
    assert sha(ext / 'priv-app/SystemUI/SystemUI.apk') == '33017b0d59e28da5db3e089a98f49601de508228a012392ee2d04c82cda3ccb1'
    run([HOST / 'fsck.erofs', '-d0', '--extract=' + str(work / 'odm-tree'), '--preserve', chain['odm']])
    outputs = {'vendor': vendor, 'vbmeta': work / 'vbmeta.img'}
    boot_policy = verify_boot_policy({**chain, 'vendor': vendor}, work)
    boot_policy.update(split_policy_selection(work))
    genfs_output = run([args.genfs_probe.resolve(strict=True), work / 'combined-boot-policy'])
    assert CONTROL_PATH + ' u:object_r:sysfs_fingerprint_sheng:s0' in genfs_output
    assert '/wakeup/wakeup2/name u:object_r:sysfs_wakeup:s0' in genfs_output
    (work / 'compiled-genfs-check.txt').write_text(genfs_output)
    merge_parent(avb, avbtool, chain['vbmeta'], [tree], outputs['vbmeta'], 'SHA256_RSA4096', work)
    complete = work / 'complete-chain'
    complete.mkdir()
    for part, path in chain.items():
        (complete / (part + '.img')).symlink_to(outputs.get(part, path).resolve())
    run([HOST / 'avbtool', 'verify_image', '--image', complete / 'vbmeta.img', '--follow_chain_partitions'])
    sources()
    validate_inputs('vendor', entries)
    validate_packaging_inputs(['vendor'], frozen)
    unchanged = [entry for entry in baseline if entry['partition'] not in outputs]
    publish_batch(workspace / 'artifacts/system-hardware-followup-sheng-r62', outputs, dict(
        revision=62, baseline_revision=61, baseline_partitions=baseline,
        baseline_manifest_sha256=sha(previous_path), unchanged_partition_files=unchanged,
        unchanged_boot_dependencies=[], entries={'vendor': entries}, partition_reports={'vendor': stage},
        original_systemui_unchanged=True, complete_avb_chain_verified=True,
        all_filesystem_stages_verified=True, normal_module_build_passed=True,
        full_product_build_passed=False, hardware_boot_tested=False, boot_policy=boot_policy,
        qti_source_service_integrated=False, installed_qti_retained=True,
        retained_qti_sha256=previous['retained_qti_sha256'],
        fingerprint_control_label_corrected=True, policy_added=[CONTROL_RULE], no_new_allow_rules=True,
        compiled_genfs_lookup_passed=True, genfs_probe_sha256=sha(args.genfs_probe),
        nonexistent_tap_sensors_removed=True, precise_wakeup_labels_integrated=True,
        touch_r50_retained=True, dolby_ui_r51_retained=True, dolby_media_r52_retained=True,
        keyboard_r53_retained=True, face_candidate_installed=False, recovery_revision_retained=59,
        sources_sha256={SOURCE_PATH: mirror['inputs'][SOURCE_PATH]['sha256']},
        packaging_inputs_sha256=frozen, build_log_sha256=sha(args.build_log),
        source_mirror_sha256=sha(args.mirror), post_audit_sha256=sha(args.audit), work_dir=str(work)))
    print('Published r62: vendor policy and matching vbmeta only', flush=True)


if __name__ == '__main__':
    main()
