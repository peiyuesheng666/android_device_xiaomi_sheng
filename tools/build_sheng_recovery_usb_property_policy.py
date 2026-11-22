#!/usr/bin/env python3
"""Qualify the USB property delta against the installed Pixel Recovery policy.

Offline only. Reproduce the retained policy byte-for-byte before applying the
device-owned macro expansion. This is not a full product build or deployment.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

TYPE = 'vendor_sheng_recovery_usb_ready_prop'
PROPERTY = 'vendor.sheng.recovery.usb_role_ready'
DECLARATION = f'vendor_public_prop({TYPE})'
CONTEXT = f'{PROPERTY} u:object_r:{TYPE}:s0 exact bool'
EXPECTED_BASE = '831e3ee0d0c8984ab6d523c5d04e1b4f823e230371bb79b0179e86735ca7afa3'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def policy_statements(expanded):
    return '\n'.join(line for line in expanded.splitlines()
                     if line.strip() and not line.lstrip().startswith('#')) + '\n'


def source_contract(device):
    policy = device / 'sepolicy/vendor'
    declaration = (policy / 'property.te').read_text()
    contexts = (policy / 'property_contexts').read_text()
    permissions = (policy / 'sheng_recovery_usb.te').read_text()
    assert declaration.count(DECLARATION) == 1
    matches = [s.strip() for s in contexts.splitlines()
               if s.split('#', 1)[0].strip().startswith(PROPERTY)]
    assert matches == [CONTEXT], 'Require one exact boolean context, not a prefix'
    lines = [s.strip() for s in permissions.splitlines()
             if s.strip() and not s.lstrip().startswith('#')]
    assert lines == ["recovery_only(`", f'set_prop(recovery, {TYPE})', "')"]
    return permissions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--out-dir', default='out-clean-ota-20261116')
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    rom = args.rom.resolve()
    out = rom / args.out_dir
    host = out / 'host/linux-x86/bin'
    intermediates = out / 'soong/.intermediates/system/sepolicy'
    device = Path(__file__).resolve().parents[1]
    permissions = source_contract(device)
    work = args.work.resolve()
    assert not work.exists(), 'Use a new evidence directory'
    work.mkdir(parents=True)
    commands = []

    def run(argv, data=None):
        result = subprocess.run(list(map(str, argv)), input=data, text=True,
                                capture_output=True, cwd=rom, timeout=180)
        commands.append(dict(argv=list(map(str, argv)), returncode=result.returncode,
                             stdout=result.stdout, stderr=result.stderr))
        (work / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        assert result.returncode == 0, result.stderr[-5000:]
        return result.stdout

    def expand(source, recovery):
        return policy_statements(run([rom / 'prebuilts/build-tools/linux-x86/bin/m4', '--fatal-warnings',
                    '-Dtarget_recovery=' + recovery,
                    rom / 'system/sepolicy/public/global_macros',
                    rom / 'system/sepolicy/public/te_macros', '-'], source))

    def compile_policy(conf, stem):
        cil, binary = work / (stem + '.cil'), work / (stem + '.policy')
        run([host / 'checkpolicy', '-C', '-M', '-L', '-c', '30', '-o', cil, conf])
        # Pixel's retained sepolicy.recovery rule has ONE CIL input. Adding the
        # Lineage genfs compat input changes the baseline and is not equivalent.
        run([host / 'secilc', '-m', '-M', 'true', '-G', '-c', '30', cil,
             '-o', binary, '-f', '/dev/null'])
        return binary

    original = intermediates / 'recovery_sepolicy.conf/android_common/sheng/recovery_sepolicy.conf'
    base_conf = work / 'base.conf'
    base_conf.write_bytes(original.read_bytes())
    base = compile_policy(base_conf, 'base')
    installed = out / 'target/product/sheng/recovery/root/sepolicy'
    assert digest(base) == digest(installed) == EXPECTED_BASE, 'Baseline mismatch: STOP'
    expanded_type = expand(DECLARATION + '\n', 'true')
    expanded_allow = expand(permissions, 'true')
    normal_allow = expand(permissions, 'false')
    assert TYPE not in normal_allow, 'Recovery grant leaked into normal Android'
    assert f'allow recovery {TYPE}:property_service set;' in expanded_allow
    assert 'vendor_default_prop' not in expanded_allow and 'permissive ' not in expanded_allow
    text = base_conf.read_text()
    assert TYPE not in text
    anchor = 'type vendor_camera_p3enable_prop,'
    assert text.count(anchor) == 1
    text = text.replace(anchor, expanded_type + '\n' + expanded_allow + '\n' + anchor)
    candidate_conf = work / 'candidate.conf'
    candidate_conf.write_text(text)
    candidate = compile_policy(candidate_conf, 'candidate')
    before = run([host / 'sepolicy-analyze', base, 'permissive'])
    after = run([host / 'sepolicy-analyze', candidate, 'permissive'])
    assert before == after, 'No new permissive domains allowed'
    contexts = []
    for partition in ('plat', 'system_ext', 'product', 'vendor', 'odm'):
        root = intermediates / ('contexts/' + partition + '_property_contexts.recovery')
        files = list(root.rglob(partition + '_property_contexts'))
        assert len(files) == 1, (partition, files)
        target = work / (partition + '_property_contexts')
        source = files[0].read_text()
        assert PROPERTY not in source
        target.write_text(source + ('\n' + CONTEXT + '\n' if partition == 'vendor' else ''))
        contexts.append(target)
    run([host / 'property_info_checker', candidate, *contexts])
    receipt = dict(passed=True, offline_only=True, flashed=False,
                   full_product_build=False, runtime_verified=False,
                   baseline_reproduced_sha256=digest(base),
                   candidate_policy_sha256=digest(candidate), candidate_policy=str(candidate),
                   candidate_vendor_property_contexts=str(work / 'vendor_property_contexts'),
                   exact_context=CONTEXT, property_info_checker_passed=True,
                   neverallows_checked=True, recovery_setter_grant_scoped=True,
                   permissive_domains_unchanged=True, permissive_domains=before.split(),
                   all_enforcing_recovery_verified=False,
                   source_sha256={str(p.relative_to(device)): digest(p) for p in
                       (device / 'sepolicy/vendor' / n for n in
                        ('property.te', 'property_contexts', 'sheng_recovery_usb.te'))},
                   retained_conf_sha256=digest(original),
                   note='Only exact USB property label/grant delta; existing permissive domains not removed.')
    (work / 'qualification.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
