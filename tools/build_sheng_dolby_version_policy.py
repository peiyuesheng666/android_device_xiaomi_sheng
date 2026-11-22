#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compile the Dolby property initializer from retained policy build commands."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import shlex
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rules', type=Path, required=True)
    parser.add_argument('--baseline-review', type=Path,
                        help='Complete binary-policy comparison against the active kernel policy')
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    workspace = source.parents[2]
    rom = Path('/root/sheng-lineage/lineage-24.0')
    host = rom / 'out/host/linux-x86/bin'
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    assert work.stat().st_dev == Path('/').stat().st_dev
    lock = (rom / 'out/.sheng-device-modules.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    rules = json.loads(args.rules.read_text())
    receipt = dict(started_utc=datetime.now(timezone.utc).isoformat(), passed=False,
                   installed=False, ninja_graph_loaded=False, neverallows_enabled=True,
                   commands=[], inputs_sha256={}, mounted_cil_sha256={},
                   rules_sha256=sha(args.rules), builder_sha256=sha(Path(__file__)))

    def run(command, label, output=None):
        command = list(map(str, command))
        result = subprocess.run(command, cwd=rom, capture_output=True, timeout=120)
        (work / (label + '.log')).write_bytes(result.stderr if output else result.stdout + result.stderr)
        receipt['commands'].append(dict(argv=command, exit_code=result.returncode))
        result.check_returncode()
        if output:
            output.write_bytes(result.stdout)
        return result.stdout

    try:
        command = rules['rule m.vendor_sepolicy.conf_android_common.conf']
        if command.endswith('.sh'):
            receipt['inputs_sha256'][str(rom / command)] = sha(rom / command)
            command = (rom / command).read_text()
        tokens = shlex.split(command[command.index('prebuilts/build-tools/linux-x86/bin/m4 '):])
        redirect = tokens.index('>')
        m4, old_conf = tokens[:redirect], rom / tokens[redirect + 1]
        assert m4[0].endswith('/m4') and '--fatal-warnings' in m4
        for value in m4:
            path = rom / value
            if path.is_file():
                receipt['inputs_sha256'][str(path)] = sha(path)
        original = work / 'baseline-vendor.conf'
        run(m4, 'baseline-source', original)
        assert original.read_bytes() == old_conf.read_bytes(), 'Retained vendor sources changed'
        final = shlex.split(rules['rule m.precompiled_sepolicy_android_common.secilc'].split(' && ', 1)[0])
        assert '-N' not in final and Path(final[0]).name == 'secilc'
        adb = workspace / 'tools/platform-tools/adb.exe'
        identity = run([adb, '-s', 'ca10ede3', 'shell',
                        'getprop ro.product.device; getprop ro.boot.slot_suffix; getenforce'], 'identity')
        assert identity.decode().splitlines() == ['sheng', '_a', 'Enforcing']
        for value in final:
            path = rom / value
            if value.endswith('.cil'):
                name = path.name
                if 'system_ext_mapping_file' in value:
                    remote = '/system_ext/etc/selinux/mapping/' + name
                elif 'product_mapping_file' in value:
                    remote = '/product/etc/selinux/mapping/' + name
                elif 'plat_mapping_file' in value:
                    remote = '/system/etc/selinux/mapping/' + name
                else:
                    part = next((part for prefix, part in (
                        ('system_ext_', 'system_ext'), ('product_', 'product'),
                        ('vendor_', 'vendor'), ('odm_', 'odm'),
                        ('plat_pub_versioned', 'vendor')) if name.startswith(prefix)), 'system')
                    remote = '/' + part + '/etc/selinux/' + name
                digest = run([adb, '-s', 'ca10ede3', 'shell', 'sha256sum ' + remote],
                             'mounted-' + path.parent.parent.name + '-' + name).decode().split()[0]
                assert digest == sha(path), remote
                receipt['mounted_cil_sha256'][remote] = digest
                receipt['inputs_sha256'][str(path)] = digest
        baseline_policy = work / 'baseline.policy'
        final[final.index('-o') + 1] = str(baseline_policy)
        run(final, 'baseline-compile')
        expected = run([adb, '-s', 'ca10ede3', 'shell',
                        'sha256sum /odm/etc/selinux/precompiled_sepolicy'], 'mounted-precompiled').decode().split()[0]
        receipt['installed_cached_policy_sha256'] = expected
        if sha(baseline_policy) != expected:
            assert args.baseline_review, 'Cached policy differs; active-policy comparison is required'
            review = json.loads(args.baseline_review.read_text())
            assert review['builder_sha256'] == sha(source / 'tools/review_sheng_policy_delta.py')
            for key in ('added_types', 'removed_types', 'added_existing_type_permissions',
                        'removed_existing_type_permissions', 'existing_type_attribute_membership_changes',
                        'existing_type_non_av_rule_forms_added', 'existing_type_non_av_rule_forms_removed',
                        'existing_role_type_statements_added', 'existing_role_type_statements_removed',
                        'other_statements_added', 'other_statements_removed'):
                assert not review[key], key
            assert review['baseline_permissive_domains'] == review['candidate_permissive_domains']
            hashes = review['inputs_and_decompiled_sha256']
            assert all(sha(Path(name)) == digest for name, digest in hashes.items())
            active = [digest for name, digest in hashes.items() if Path(name).name == 'active-kernel.policy']
            rebuilt = [digest for name, digest in hashes.items() if Path(name).name == 'baseline.policy']
            assert len(active) == len(rebuilt) == 1 and rebuilt[0] == sha(baseline_policy)
            live = run([adb, '-s', 'ca10ede3', 'shell', 'sha256sum /sys/fs/selinux/policy'],
                       'active-policy-identity').decode().split()[0]
            assert live == active[0]
            receipt.update(active_policy_semantically_identical=True, active_policy_sha256=live,
                           baseline_review_sha256=sha(args.baseline_review),
                           existing_permissive_domains=review['baseline_permissive_domains'])
        relative = 'sepolicy/vendor/vendor_init.te'
        mirrored = rom / 'device/xiaomi/sheng' / relative
        before, after = mirrored.read_bytes(), (source / relative).read_bytes()
        meaningful = lambda data: [line for line in data.decode().splitlines()
                                   if line.strip() and not line.lstrip().startswith('#')]
        new_rule = 'set_prop(vendor_init, vendor_sheng_dolby_prop)'
        assert meaningful(after) == meaningful(before) + [new_rule]
        (work / 'before-vendor_init.te').write_bytes(before)
        mirrored.write_bytes(after)
        receipt['changed_source'] = dict(path=relative, before_sha256=hashlib.sha256(before).hexdigest(),
                                        after_sha256=sha(mirrored))
        conf = work / 'vendor.conf'
        run(m4, 'candidate-source', conf)
        unversioned = work / 'vendor.unversioned.cil'
        run([host / 'checkpolicy', '-C', '-M', '-L', '-c', '30', '-o', unversioned, conf], 'checkpolicy')
        policy = rom / 'out/soong/.intermediates/system/sepolicy'
        mask = policy / 'reqd_policy_mask.cil/android_common/reqd_policy_mask.cil'
        public = policy / 'pub_policy.cil/android_common/sheng/pub_policy.cil'
        versioned = policy / 'plat_pub_versioned.cil/android_common/sheng/plat_pub_versioned.cil'
        for path in (mask, public, versioned):
            receipt['inputs_sha256'][str(path)] = sha(path)
        run([host / 'build_sepolicy', 'filter_out', '-f', mask, '-t', unversioned], 'filter-mask')
        version = (rom / 'out/target/product/sheng/vendor/etc/selinux/plat_sepolicy_vers.txt').read_text().strip()
        mapping, attributed = work / 'mapping.cil', work / 'attributed.cil'
        run([host / 'version_policy', '-b', public, '-n', version, '-o', mapping, '-m'], 'mapping')
        run([host / 'version_policy', '-b', public, '-n', version, '-t', unversioned,
             '-o', attributed], 'version-policy')
        run([host / 'build_sepolicy', 'filter_out', '-f', mapping, '-t', attributed], 'filter-mapping')
        vendor = work / 'vendor_sepolicy.cil'
        vendor.write_bytes(mapping.read_bytes() + attributed.read_bytes())
        run([host / 'build_sepolicy', 'filter_out', '-f', versioned, '-t', vendor], 'filter-versioned')
        old_vendor = 'out/soong/.intermediates/system/sepolicy/vendor_sepolicy.cil/android_common/sheng/vendor_sepolicy.cil'
        assert final.count(old_vendor) == 1
        final[final.index(old_vendor)] = str(vendor)
        candidate = work / 'precompiled_sepolicy'
        final[final.index('-o') + 1] = str(candidate)
        run(final, 'candidate-neverallows')
        for name, digest in receipt['inputs_sha256'].items():
            assert sha(Path(name)) == (receipt['changed_source']['after_sha256']
                                      if Path(name) == mirrored else digest), name
        assert sha(source / relative) == sha(mirrored)
        receipt.update(passed=True, baseline_reproduced_sha256=sha(baseline_policy),
                       outputs={path.name: dict(path=str(path), sha256=sha(path), bytes=path.stat().st_size)
                                for path in (vendor, candidate)})
    except BaseException as error:
        receipt['error'] = repr(error)
        raise
    finally:
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        (work / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(dict(passed=True, receipt=str(work / 'receipt.json'))))


if __name__ == '__main__':
    main()
