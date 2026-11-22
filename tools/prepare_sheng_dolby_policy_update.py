#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Qualify the Dolby initializer policy against the current split-policy boot."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess

from build_sheng_dolby_version_policy import sha


def validate(device, receipt_path):
    receipt = json.loads(receipt_path.read_text())
    if receipt.get('kind') in ('vendor-property-policy', 'hid-input-policy'):
        from build_sheng_vendor_property_policy import validate as validate_properties
        return validate_properties(device, receipt_path)
    assert receipt['passed'] and receipt['kind'] == 'dolby-version-policy'
    assert receipt['existing_precompiled_cache_ineligible']
    assert any(row['current'] != row['cached'] for row in receipt['cache_hashes'].values())
    assert all(re.fullmatch(r'[0-9a-f]{64}', value)
               for row in receipt['cache_hashes'].values() for value in row.values())
    for path_key, hash_key in (('build_receipt', 'build_receipt_sha256'),
                               ('permission_review', 'permission_review_sha256')):
        assert sha(Path(receipt[path_key])) == receipt[hash_key]
    build = json.loads(Path(receipt['build_receipt']).read_text())
    review = json.loads(Path(receipt['permission_review']).read_text())
    assert build['passed'] and build['neverallows_enabled'] and not build['ninja_graph_loaded']
    assert build['active_policy_semantically_identical']
    assert build['active_policy_sha256'] == receipt['active_policy_sha256']
    assert build['builder_sha256'] == sha(device / 'tools/build_sheng_dolby_version_policy.py')
    assert review['builder_sha256'] == sha(device / 'tools/review_sheng_policy_delta.py')
    changed = build['changed_source']
    assert changed['path'] == 'sepolicy/vendor/vendor_init.te'
    assert sha(device / changed['path']) == changed['after_sha256']
    for name, digest in build['inputs_sha256'].items():
        wanted = changed['after_sha256'] if name.endswith('/device/xiaomi/sheng/' + changed['path']) else digest
        assert sha(Path(name)) == wanted, name
    for name, digest in review['inputs_and_decompiled_sha256'].items():
        assert sha(Path(name)) == digest
    outputs = build['outputs']
    assert set(outputs) == {'vendor_sepolicy.cil', 'precompiled_sepolicy'}
    for value in outputs.values():
        assert sha(Path(value['path'])) == value['sha256']
    reviewed = review['inputs_and_decompiled_sha256']
    assert reviewed[outputs['precompiled_sepolicy']['path']] == outputs['precompiled_sepolicy']['sha256']
    baseline_policy = Path(receipt['build_receipt']).parent / 'baseline.policy'
    assert reviewed[str(baseline_policy)] == build['baseline_reproduced_sha256'] == sha(baseline_policy)
    expected = {('allow', 'vendor_init', 'vendor_sheng_dolby_prop', 'file', permission)
                for permission in ('getattr', 'map', 'open', 'read')}
    expected.add(('allow', 'vendor_init', 'vendor_sheng_dolby_prop', 'property_service', 'set'))
    actual = {tuple(row[key] for key in ('kind', 'source', 'target', 'tclass', 'permission'))
              for row in review['added_existing_type_permissions']}
    assert actual == expected
    for key in ('added_types', 'removed_types', 'removed_existing_type_permissions',
                'existing_type_attribute_membership_changes', 'existing_type_non_av_rule_forms_added',
                'existing_type_non_av_rule_forms_removed', 'existing_role_type_statements_added',
                'existing_role_type_statements_removed', 'other_statements_added', 'other_statements_removed'):
        assert not review[key], key
    assert review['baseline_permissive_domains'] == review['candidate_permissive_domains']
    assert set(receipt['entries']) == {'etc/selinux/vendor_sepolicy.cil'}
    assert receipt['entries']['etc/selinux/vendor_sepolicy.cil'] == outputs['vendor_sepolicy.cil']
    for name, digest in receipt['source_sha256'].items():
        assert sha(device / name) == digest
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    device = Path(__file__).resolve().parents[1]
    workspace = device.parents[2]
    adb = workspace / 'tools/platform-tools/adb.exe'
    baseline = json.loads(args.baseline.read_text())
    assert baseline['complete_avb_chain_verified']
    build = json.loads(args.build.read_text())
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    commands = []

    def shell(command):
        result = subprocess.run([str(adb), '-s', 'ca10ede3', 'shell', command],
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        commands.append(dict(command=command, exit_code=result.returncode, output=result.stdout + result.stderr))
        result.check_returncode()
        return result.stdout.strip()

    assert shell('getprop ro.product.device; getprop ro.boot.slot_suffix; getenforce').splitlines() == [
        'sheng', '_a', 'Enforcing']
    assert shell('sha256sum /sys/fs/selinux/policy').split()[0] == build['active_policy_sha256']
    hashes = {}
    for part in ('system_ext', 'product'):
        current = '/' + part + '/etc/selinux/' + part + '_sepolicy_and_mapping.sha256'
        cached = '/odm/etc/selinux/precompiled_sepolicy.' + part + '_sepolicy_and_mapping.sha256'
        hashes[part] = dict(current=shell('cat ' + current), cached=shell('cat ' + cached))
    old_vendor = Path(baseline['work_dir']) / 'vendor-tree/etc/selinux/vendor_sepolicy.cil'
    before = build['mounted_cil_sha256']['/vendor/etc/selinux/vendor_sepolicy.cil']
    assert sha(old_vendor) == shell('sha256sum /vendor/etc/selinux/vendor_sepolicy.cil').split()[0] == before
    receipt = dict(kind='dolby-version-policy', date_utc=datetime.now(timezone.utc).isoformat(),
                   passed=True, baseline_manifest=str(args.baseline), baseline_sha256=sha(args.baseline),
                   build_receipt=str(args.build), build_receipt_sha256=sha(args.build),
                   permission_review=str(args.review), permission_review_sha256=sha(args.review),
                   active_policy_sha256=build['active_policy_sha256'], cache_hashes=hashes,
                   existing_precompiled_cache_ineligible=True, vendor_cil_before_sha256=before,
                   entries={'etc/selinux/vendor_sepolicy.cil': build['outputs']['vendor_sepolicy.cil']},
                   source_sha256={name: sha(device / name) for name in (
                       'sepolicy/vendor/vendor_init.te', 'tools/build_sheng_dolby_version_policy.py',
                       'tools/prepare_sheng_dolby_policy_update.py', 'tools/review_sheng_policy_delta.py')},
                   commands=commands, installed=False, ninja_graph_loaded=False)
    path = output / 'receipt.json'
    path.write_text(json.dumps(receipt, indent=2) + '\n')
    try:
        validate(device, path)
    except BaseException as error:
        receipt.update(passed=False, error=repr(error))
        path.write_text(json.dumps(receipt, indent=2) + '\n')
        raise
    print(json.dumps(dict(passed=True, receipt=str(path))))


if __name__ == '__main__':
    main()
