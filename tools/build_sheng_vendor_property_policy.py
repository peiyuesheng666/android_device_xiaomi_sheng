#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build and qualify scoped vendor policy repairs from retained policy commands."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import subprocess


CHANGES = {
    'sepolicy/vendor/hal_sheng_dolby.te': (
        ['get_prop(hal_sheng_dolby_default, vendor_audio_prop)'],
        ['set_prop(hal_sheng_dolby_default, vendor_audio_prop)']),
    'sepolicy/vendor/vendor_init.te': (
        [], ['set_prop(vendor_init, vendor_qcc_prop)']),
    'sepolicy/vendor/vendorcodec.te': (
        [], ['get_prop(vendorcodec, vendor_audio_prop)']),
}
OTHER_CHANGES = (
    'added_types', 'removed_types', 'removed_existing_type_permissions',
    'existing_type_attribute_membership_changes', 'existing_type_non_av_rule_forms_added',
    'existing_type_non_av_rule_forms_removed', 'existing_role_type_statements_added',
    'existing_role_type_statements_removed', 'other_statements_added', 'other_statements_removed',
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def changes_for(profile):
    if profile == 'hid-input':
        from sheng_hid_policy_spec import CHANGES as changes
        return changes
    assert profile == 'vendor-properties'
    return CHANGES


def expected_permissions(profile='vendor-properties'):
    if profile == 'hid-input':
        return set()  # The dedicated new type is checked separately.
    assert profile == 'vendor-properties'
    rules = {
        ('allow', 'hal_sheng_dolby_default', 'property_socket', 'sock_file', 'write'),
        ('allow', 'hal_sheng_dolby_default', 'init', 'unix_stream_socket', 'connectto'),
        ('allow', 'hal_sheng_dolby_default', 'vendor_audio_prop', 'property_service', 'set'),
        ('allow', 'vendor_init', 'vendor_qcc_prop', 'property_service', 'set'),
    }
    for source, target in (('vendor_init', 'vendor_qcc_prop'), ('vendorcodec', 'vendor_audio_prop')):
        rules.update(('allow', source, target, 'file', permission)
                     for permission in ('getattr', 'map', 'open', 'read'))
    return rules


def check_review(review, expected, profile='vendor-properties'):
    if profile == 'hid-input':
        from sheng_hid_policy_spec import check_review as check_hid
        return check_hid(review, expected)
    actual = {tuple(row[key] for key in ('kind', 'source', 'target', 'tclass', 'permission'))
              for row in review['added_existing_type_permissions']}
    assert actual == expected, dict(unexpected=sorted(actual - expected), missing=sorted(expected - actual))
    for key in OTHER_CHANGES:
        assert not review[key], key
    assert review['baseline_permissive_domains'] == review['candidate_permissive_domains']


def validate(device, receipt_path):
    receipt = json.loads(receipt_path.read_text())
    profile = receipt.get('profile', 'vendor-properties')
    changes = changes_for(profile)
    assert receipt['kind'] == ('hid-input-policy' if profile == 'hid-input' else 'vendor-property-policy')
    assert receipt['passed']
    assert receipt['neverallows_enabled'] and not receipt['ninja_graph_loaded']
    assert receipt['existing_precompiled_cache_ineligible']
    assert any(row['current'] != row['cached'] for row in receipt['cache_hashes'].values())
    assert all(re.fullmatch(r'[0-9a-f]{64}', value)
               for row in receipt['cache_hashes'].values() for value in row.values())
    assert sha(Path(receipt['baseline_manifest'])) == receipt['baseline_sha256']
    assert sha(Path(receipt['retained_build'])) == receipt['retained_build_sha256']
    for name, digest in receipt['inputs_sha256'].items():
        assert sha(Path(name)) == digest, name
    for name, digest in receipt['source_sha256'].items():
        assert sha(device / name) == digest, name
    for change in receipt['changed_sources'].values():
        assert sha(Path(change['before_path'])) == change['before_sha256']
    assert set(receipt['changed_sources']) == set(changes)
    outputs = receipt['outputs']
    assert set(outputs) == {'vendor_sepolicy.cil', 'precompiled_sepolicy', 'baseline.policy', 'active-kernel.policy'}
    for row in outputs.values():
        assert sha(Path(row['path'])) == row['sha256']
    assert receipt['active_policy_sha256'] == outputs['active-kernel.policy']['sha256']
    for field, expected in (('baseline_review', set()), ('permission_review', expected_permissions(profile))):
        path = Path(receipt[field])
        assert sha(path) == receipt[field + '_sha256']
        review = json.loads(path.read_text())
        assert review['builder_sha256'] == sha(device / 'tools/review_sheng_policy_delta.py')
        for name, digest in review['inputs_and_decompiled_sha256'].items():
            assert sha(Path(name)) == digest, name
        names = ('active-kernel.policy', 'baseline.policy') if field == 'baseline_review' else (
            'baseline.policy', 'precompiled_sepolicy')
        for name in names:
            row = outputs[name]
            assert review['inputs_and_decompiled_sha256'][row['path']] == row['sha256']
        check_review(review, expected, profile if field == 'permission_review' else 'vendor-properties')
    assert receipt['entries'] == {'etc/selinux/vendor_sepolicy.cil': outputs['vendor_sepolicy.cil']}
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('vendor-properties', 'hid-input'), default='vendor-properties')
    parser.add_argument('--retained-build', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    changes = changes_for(args.profile)
    assert __debug__
    device = Path(__file__).resolve().parents[1]
    workspace = device.parents[2]
    rom = Path('/root/sheng-lineage/lineage-24.0')
    host = rom / 'out/host/linux-x86/bin'
    work = args.work.resolve()
    assert work.parent == Path('/root/sheng-lineage/hardware-diagnostics')
    work.mkdir(exist_ok=False)
    assert work.stat().st_dev == Path('/').stat().st_dev
    lock = (rom / 'out/.sheng-device-modules.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    receipt = dict(kind='hid-input-policy' if args.profile == 'hid-input' else 'vendor-property-policy',
                   profile=args.profile, passed=False, installed=False,
                   started_utc=datetime.now(timezone.utc).isoformat(), ninja_graph_loaded=False,
                   neverallows_enabled=True, commands=[], inputs_sha256={}, changed_sources={})
    receipt_path = work / 'receipt.json'

    def save():
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')

    def run(command, label, output=None):
        command = list(map(str, command))
        result = subprocess.run(command, cwd=rom, capture_output=True, timeout=180)
        (work / (label + '.log')).write_bytes(result.stderr if output else result.stdout + result.stderr)
        receipt['commands'].append(dict(label=label, argv=command, exit_code=result.returncode))
        save()
        result.check_returncode()
        if output:
            output.write_bytes(result.stdout)
        return result.stdout

    adb = workspace / 'tools/platform-tools/adb.exe'

    def shell(command, label):
        return run([adb, '-s', 'ca10ede3', 'shell', command], label).decode().strip()

    def remember(path):
        path = path if path.is_absolute() else rom / path
        receipt['inputs_sha256'][str(path)] = sha(path)

    def describe(path):
        return dict(path=str(path), sha256=sha(path), bytes=path.stat().st_size)

    try:
        retained = json.loads(args.retained_build.read_text())
        assert retained['passed'] and retained['neverallows_enabled'] and not retained['ninja_graph_loaded']
        baseline = json.loads(args.baseline.read_text())
        assert baseline['complete_avb_chain_verified']
        receipt.update(retained_build=str(args.retained_build.resolve()),
                       retained_build_sha256=sha(args.retained_build),
                       baseline_manifest=str(args.baseline.resolve()), baseline_sha256=sha(args.baseline))
        m4 = next(row['argv'] for row in retained['commands'] if Path(row['argv'][0]).name == 'm4')[:]
        final = next(row['argv'] for row in retained['commands'] if Path(row['argv'][0]).name == 'secilc')[:]
        assert '--fatal-warnings' in m4 and '-N' not in final
        assert shell('getprop ro.product.device; getprop ro.boot.slot_suffix; getenforce; id -u',
                     'identity').splitlines() == ['sheng', '_a', 'Enforcing', '0']
        active = work / 'active-kernel.policy'
        run([adb, '-s', 'ca10ede3', 'exec-out', 'cat', '/sys/fs/selinux/policy'], 'active-policy', active)
        receipt['active_policy_sha256'] = sha(active)
        cache_hashes = {}
        for part in ('system_ext', 'product'):
            cache_hashes[part] = dict(
                current=shell('cat /' + part + '/etc/selinux/' + part + '_sepolicy_and_mapping.sha256', part + '-current-hash'),
                cached=shell('cat /odm/etc/selinux/precompiled_sepolicy.' + part + '_sepolicy_and_mapping.sha256', part + '-cached-hash'))
        assert any(row['current'] != row['cached'] for row in cache_hashes.values())
        receipt.update(cache_hashes=cache_hashes, existing_precompiled_cache_ineligible=True)
        mounted = {}
        for index, value in enumerate(final):
            if not value.endswith('.cil'):
                continue
            path = rom / value
            name = path.name
            if 'system_ext_mapping_file' in value:
                remote = '/system_ext/etc/selinux/mapping/' + name
            elif 'product_mapping_file' in value:
                remote = '/product/etc/selinux/mapping/' + name
            elif 'plat_mapping_file' in value:
                remote = '/system/etc/selinux/mapping/' + name
            else:
                part = next((part for prefix, part in (
                    ('system_ext_', 'system_ext'), ('product_', 'product'), ('vendor_', 'vendor'),
                    ('odm_', 'odm'), ('plat_pub_versioned', 'vendor')) if name.startswith(prefix)), 'system')
                remote = '/' + part + '/etc/selinux/' + name
            digest = shell('sha256sum ' + remote, 'mounted-' + str(index)).split()[0]
            mounted[remote] = digest
            if name == 'vendor_sepolicy.cil':
                vendor_index = index
                current_vendor = Path(baseline['work_dir']) / 'vendor-tree/etc/selinux/vendor_sepolicy.cil'
                assert sha(current_vendor) == digest
            else:
                assert sha(path) == digest, remote
                remember(path)
        receipt.update(mounted_cil_sha256=mounted,
                       vendor_cil_before_sha256=mounted['/vendor/etc/selinux/vendor_sepolicy.cil'])
        before_paths, after_paths = {}, {}
        meaningful = lambda data: [line for line in data.decode().splitlines()
                                   if line.strip() and not line.lstrip().startswith('#')]
        for relative, (removed, added) in changes.items():
            token = 'device/xiaomi/sheng/' + relative
            if token not in m4 and not (rom / token).exists():
                assert not removed and token.endswith('.te')
                position = max(i for i, value in enumerate(m4) if value.endswith('.te')) + 1
                m4.insert(position, token)
                receipt.setdefault('new_policy_inputs', []).append(token)
            assert m4.count(token) == 1, relative
            before = (rom / token).read_bytes() if (rom / token).exists() else b''
            after = (device / relative).read_bytes()
            old_lines, new_lines = meaningful(before), meaningful(after)
            assert all(old_lines.count(line) == 1 for line in removed)
            assert sorted(new_lines) == sorted([line for line in old_lines if line not in removed] + added)
            snapshot = work / 'source-before' / relative
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes(before)
            # libsepol line markers require paths that its CIL lexer can parse.
            # Keep both compiler inputs on the native filesystem with ASCII paths.
            candidate_source = work / 'source-after' / relative
            candidate_source.parent.mkdir(parents=True, exist_ok=True)
            candidate_source.write_bytes(after)
            before_paths[token], after_paths[token] = str(snapshot), str(candidate_source)
            receipt['changed_sources'][relative] = dict(before_path=str(snapshot), before_sha256=sha(snapshot),
                                                       after_sha256=sha(device / relative))
        for token in m4:
            if token.startswith('device/xiaomi/sheng/') and token not in before_paths:
                source = device / token.removeprefix('device/xiaomi/sheng/')
                assert source.is_file() and sha(source) == sha(rom / token), token
        for command in ([before_paths.get(token, token) for token in m4],
                        [after_paths.get(token, token) for token in m4]):
            for token in command:
                path = Path(token)
                if (path if path.is_absolute() else rom / path).is_file():
                    remember(path)
        policy = rom / 'out/soong/.intermediates/system/sepolicy'
        mask = policy / 'reqd_policy_mask.cil/android_common/reqd_policy_mask.cil'
        public = policy / 'pub_policy.cil/android_common/sheng/pub_policy.cil'
        versioned = policy / 'plat_pub_versioned.cil/android_common/sheng/plat_pub_versioned.cil'
        version_file = rom / 'out/target/product/sheng/vendor/etc/selinux/plat_sepolicy_vers.txt'
        version = version_file.read_text().strip()
        for path in (mask, public, versioned, version_file, Path(final[0]),
                     host / 'checkpolicy', host / 'build_sepolicy', host / 'version_policy'):
            remember(path)

        def compile_vendor(label, replacements, binary):
            folder = work / label
            folder.mkdir()
            conf, unversioned = folder / 'vendor.conf', folder / 'unversioned.cil'
            run([replacements.get(token, token) for token in m4], label + '-source', conf)
            run([host / 'checkpolicy', '-C', '-M', '-L', '-c', '30', '-o', unversioned, conf], label + '-checkpolicy')
            run([host / 'build_sepolicy', 'filter_out', '-f', mask, '-t', unversioned], label + '-mask')
            mapping, attributed, vendor = folder / 'mapping.cil', folder / 'attributed.cil', folder / 'vendor_sepolicy.cil'
            run([host / 'version_policy', '-b', public, '-n', version, '-o', mapping, '-m'], label + '-mapping')
            run([host / 'version_policy', '-b', public, '-n', version, '-t', unversioned, '-o', attributed], label + '-version')
            run([host / 'build_sepolicy', 'filter_out', '-f', mapping, '-t', attributed], label + '-filter-mapping')
            vendor.write_bytes(mapping.read_bytes() + attributed.read_bytes())
            run([host / 'build_sepolicy', 'filter_out', '-f', versioned, '-t', vendor], label + '-filter-versioned')
            command = final[:]
            command[vendor_index] = str(vendor)
            command[command.index('-o') + 1] = str(binary)
            run(command, label + '-neverallows')
            return vendor

        original = work / 'baseline.policy'
        compile_vendor('baseline', before_paths, original)
        reviewer = device / 'tools/review_sheng_policy_delta.py'

        def review(label, before, after, expected):
            folder = work.with_name(work.name + '-' + label)
            run(['python3', reviewer, '--baseline', before, '--candidate', after, '--work', folder], label)
            path = folder / 'policy-delta.json'
            check_review(json.loads(path.read_text()), expected,
                         args.profile if label == 'permission-review' else 'vendor-properties')
            receipt[label.replace('-', '_')] = str(path)
            receipt[label.replace('-', '_') + '_sha256'] = sha(path)

        review('baseline-review', active, original, set())
        candidate = work / 'precompiled_sepolicy'
        vendor = compile_vendor('candidate', after_paths, candidate)
        review('permission-review', original, candidate, expected_permissions(args.profile))
        assert shell('sha256sum /sys/fs/selinux/policy', 'active-policy-after').split()[0] == sha(active)
        receipt.update(outputs={path.name: describe(path) for path in (vendor, candidate, original, active)},
                       entries={'etc/selinux/vendor_sepolicy.cil': describe(vendor)},
                       source_sha256={relative: sha(device / relative) for relative in (*changes,
                           'tools/build_sheng_vendor_property_policy.py', 'tools/prepare_sheng_dolby_policy_update.py',
                           'tools/review_sheng_policy_delta.py', 'tools/package_sheng_codec2_service.py',
                           *(['tools/sheng_hid_policy_spec.py'] if args.profile == 'hid-input' else []))}, passed=True)
        save()
        validate(device, receipt_path)
        for relative, digest in receipt['source_sha256'].items():
            target = rom / 'device/xiaomi/sheng' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((device / relative).read_bytes())
            assert sha(target) == digest
        receipt['source_mirror_updated'] = True
    except BaseException as error:
        receipt.update(passed=False, error=repr(error))
        raise
    finally:
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        save()
    print(json.dumps(dict(passed=True, receipt=str(receipt_path), profile=args.profile,
                          added_existing_type_permissions=len(expected_permissions(args.profile)))))


if __name__ == '__main__':
    main()
