#!/usr/bin/env python3
"""Compile a source-backed Recovery-only delta against the verified r13 policy.

The full Soong graph is currently resource limited. Reproduce the installed
policy first, then add only these device source statements to its retained
policy.conf. Both builds retain checkpolicy and secilc neverallow checks.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile

DEVICE = Path(__file__).resolve().parents[1]
WORKSPACE = DEVICE.parents[2]
ROM = Path('/root/sheng-lineage/lineage-24.0')
OUT = Path(tempfile.mkdtemp(prefix='recovery-firmware-r54-', dir='/root/sheng-lineage'))
EXPECTED = 'f0ddaed385f175c06966f0f6c0989604037d9e32d0e782e38755dfc73fa375e1'
TYPE = 'vendor_sysfs_sheng_firmware_path'
CONF = ROM/'out/soong/.intermediates/system/sepolicy/recovery_sepolicy.conf/android_common/sheng/recovery_sepolicy.conf'
GENFS = ROM/'out/soong/.intermediates/system/sepolicy/compat/plat_sepolicy_genfs_202604.cil/android_arm64_armv8-2a-dotprod_kryo/plat_sepolicy_genfs_202604.cil'
HOST = ROM/'out/host/linux-x86/bin'
commands = []

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def run(args, **kwargs):
    result = subprocess.run(list(map(str, args)), cwd=ROM, capture_output=True,
                            text=True, **kwargs)
    commands.append({'command': list(map(str, args)), 'returncode': result.returncode,
                     'stdout': result.stdout, 'stderr': result.stderr})
    (OUT/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
    if result.returncode:
        raise RuntimeError(result.stderr[-6000:]+result.stdout[-6000:])
    return result.stdout

def compile_policy(conf, stem):
    cil, policy = OUT/(stem+'.cil'), OUT/(stem+'.policy')
    run([HOST/'checkpolicy', '-C', '-M', '-L', '-c', '30', '-o', cil, conf])
    run([HOST/'secilc', '-m', '-M', 'true', '-G', '-c', '30', cil, GENFS,
         '-o', policy, '-f', '/dev/null'])
    return policy

audit_path = Path('/root/sheng-lineage/hardware-diagnostics/sheng-pen-settings-20261112/prebuild-upstream-audit-latest.json')
audit = json.loads(audit_path.read_text())
assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
base_conf = OUT/'base.conf'
base_conf.write_bytes(CONF.read_bytes())
base = compile_policy(base_conf, 'base')
assert sha(base) == EXPECTED, 'Retained policy.conf does not reproduce installed Recovery'

declaration = 'type '+TYPE+', fs_type, sysfs_type;'
init_allow = 'allow init '+TYPE+':file { open write };'
read_allow = 'allow recovery '+TYPE+':file r_file_perms;'
label = 'genfscon sysfs /module/firmware_class/parameters/path u:object_r:'+TYPE+':s0'
sources = {
    'sepolicy/vendor/file.te': declaration,
    'sepolicy/vendor/init.te': init_allow+'\n'+read_allow,
    'sepolicy/vendor/genfs_contexts': label,
}
for relative, snippet in sources.items():
    assert snippet in (DEVICE/relative).read_text(), relative
scope_checks = {}
for recovery in ('false', 'true'):
    expanded_sources = {}
    for relative, snippet in sources.items():
        expanded_source = run([
            ROM/'prebuilts/build-tools/linux-x86/bin/m4', '--fatal-warnings',
            '-Dtarget_recovery='+recovery,
            ROM/'system/sepolicy/public/global_macros',
            ROM/'system/sepolicy/public/te_macros', DEVICE/relative,
        ])
        assert (TYPE in expanded_source) == (recovery == 'true'), relative
        expanded_sources[relative] = hashlib.sha256(expanded_source.encode()).hexdigest()
    scope_checks[recovery] = expanded_sources
expanded = run([ROM/'prebuilts/build-tools/linux-x86/bin/m4', '--fatal-warnings',
                ROM/'system/sepolicy/public/global_macros', '-'], input=read_allow+'\n')
expanded = '\n'.join(line for line in expanded.splitlines()
                     if line.strip() and not line.lstrip().startswith('#')).strip()
assert expanded.startswith('allow recovery '+TYPE+':file {') and expanded.endswith('};')

text = base_conf.read_text()
assert TYPE not in text
type_anchor = 'type vendor_proc_sheng_touch, fs_type, proc_type;'
allow_anchor = 'allow init init:capability { sys_module };'
genfs_anchor = 'genfscon sysfs /devices/platform/soc/soc:fingerprint_fpc u:object_r:sysfs_fingerprint_sheng:s0'
for anchor in (type_anchor, allow_anchor, genfs_anchor):
    assert text.count(anchor) == 1, anchor
text = text.replace(type_anchor, type_anchor+'\n'+declaration)
text = text.replace(allow_anchor, allow_anchor+'\n'+init_allow+'\n'+expanded)
text = text.replace(genfs_anchor, label+'\n'+genfs_anchor)
candidate_conf = OUT/'candidate.conf'
candidate_conf.write_text(text)
candidate = compile_policy(candidate_conf, 'candidate')
before = run([HOST/'sepolicy-analyze', base, 'permissive'])
after = run([HOST/'sepolicy-analyze', candidate, 'permissive'])
assert before == after, 'No new permissive domains are permitted'
run(['/bin/bash', '-n', DEVICE/'rootdir/recovery/hardware.sh'])
receipt = {
    'kind': 'Recovery-only source delta with reproduced installed-policy baseline',
    'full_product_build_passed': False,
    'baseline_policy_sha256': sha(base), 'candidate_policy_sha256': sha(candidate),
    'neverallows_enforced': True, 'permissive_domains_unchanged': True,
    'recovery_only_type_label_and_permissions_verified': True,
    'source_macro_expansion_sha256': scope_checks,
    'existing_permissive_domains': before.splitlines(),
    'upstream_audit_sha256': sha(audit_path),
    'sources': {relative: sha(DEVICE/relative) for relative in sources},
    'hardware_script_sha256': sha(DEVICE/'rootdir/recovery/hardware.sh'),
    'policy': str(candidate), 'work': str(OUT),
}
(OUT/'build-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
review = WORKSPACE/'reports/device/20261112-recovery-pen'
review.mkdir(parents=True, exist_ok=True)
(review/'policy-build-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
print(json.dumps(receipt, indent=2))
