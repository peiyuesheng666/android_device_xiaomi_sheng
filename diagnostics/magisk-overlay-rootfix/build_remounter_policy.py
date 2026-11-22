#!/usr/bin/env python3
"""Build isolated device remounter policy with retained Android policy rules.

Keeps neverallow checking enabled. Does not modify product policy or sources.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shlex
import subprocess
import sys
import tempfile

from storage_guard import require_build_space

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'tools'))
from build_sheng_fstab_variants import blocks


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rom', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    rom, out = args.rom.resolve(strict=True), args.output.resolve()
    storage = require_build_space(out)
    out.mkdir(parents=True, exist_ok=False)
    soong = rom / 'out-clean-ota-20261116/soong'
    rel = 'out-clean-ota-20261116/soong/.intermediates/system/sepolicy/'
    old_dir = rel + 'system_ext_sepolicy.conf/android_common'
    old_conf = old_dir + '/sheng/system_ext_sepolicy.conf'
    old_cil = rel + 'system_ext_sepolicy.cil/android_common/sheng/system_ext_sepolicy.cil'
    old_binary = rel + 'precompiled_sepolicy/android_common/sheng/precompiled_sepolicy'
    source = HERE.parents[1] / 'interfaces/compat/overlay-remounter/sepolicy/system_ext/private/sheng_overlay_remounter.te'
    # secilc's high-level line-mark parser rejects non-ASCII source filenames.
    # Preserve source bytes, not policy semantics, when staging an ASCII path.
    temporary = tempfile.TemporaryDirectory(prefix='sheng-remounter-policy-')
    owned = Path(temporary.name) / source.name
    owned.write_bytes(source.read_bytes())
    (out / 'policy-source.te').write_bytes(source.read_bytes())
    # Pin all existing policy files that the replay would otherwise write.
    originals = {str(p): sha(p) for p in (rom / old_conf, rom / old_cil, rom / old_binary)}
    receipts = []

    def run(command, name):
        (out / (name + '.sh')).write_text(command + '\n')
        p = subprocess.run(['/bin/sh', '-ec', command], cwd=rom, capture_output=True)
        (out / (name + '.stdout')).write_bytes(p.stdout)
        (out / (name + '.stderr')).write_bytes(p.stderr)
        receipts.append(dict(name=name, command=command, returncode=p.returncode))
        (out / 'commands.json').write_text(json.dumps(receipts, indent=2))
        if p.returncode:
            raise RuntimeError(f'{name} failed ({p.returncode}); see {out / (name + ".stderr")}')

    script = soong / 'rule_builder_scripts/6a22edbd50506d95308847c5a147a005a877557917f0bb17f6096a9d13eb2b50.sh'
    text = script.read_text()
    anchor = 'system/sepolicy/private/roles_decl '
    assert text.count(anchor) == 1
    text = text.replace(anchor, shlex.quote(str(owned)) + ' ' + old_dir + '/newline ' + anchor)
    text = text.replace(old_dir, str(out / 'transform'))
    (out / 'transform/sheng').mkdir(parents=True)
    run(text, '01-transform')

    def rule(graph, name):
        block = next(b for b in blocks(soong / graph) if b[0] == 'rule ' + name)
        line = next(s for s in block if s.strip().startswith('command = '))
        return line.strip()[len('command = '):].split(' # hash of input list:', 1)[0]

    new_conf = str(out / 'transform/sheng/system_ext_sepolicy.conf')
    new_cil = str(out / 'system_ext_sepolicy.cil')
    text = rule('build.custom_sheng.9.ninja', 'm.system_ext_sepolicy.cil_android_common.cil')
    text = text.replace(old_conf, new_conf).replace(old_cil, new_cil)
    run(text, '02-compile-filter')
    text = rule('build.custom_sheng.8.ninja', 'm.precompiled_sepolicy_android_common.secilc')
    text = text.replace(old_cil, new_cil).replace(old_binary, str(out / 'precompiled_sepolicy'))
    assert ' -N ' not in text, 'Neverallow checks must remain enabled'
    run(text, '03-full-policy-neverallows')
    # Qualify the actual file-context addition too, not just the TE rules.
    contexts = HERE.parents[1] / 'interfaces/compat/overlay-remounter/sepolicy/system_ext/private/file_contexts'
    original_contexts = (soong / '.intermediates/system/sepolicy/file_contexts.concat.tmp/'
                         'android_common/gen/file_contexts.concat.tmp')
    contexts_hash = sha(original_contexts)
    combined_contexts = out / 'file_contexts'
    combined_contexts.write_bytes(original_contexts.read_bytes().rstrip() + b'\n' + contexts.read_bytes())
    expected_contexts = out / 'file_contexts.test'
    expected_contexts.write_text(
        '/second_stage_resources tmpfs\n'
        '/second_stage_resources/overlay_remounter overlay_remounter_exec\n'
        '/second_stage_resources/sheng-remount sheng_overlay_staging_file\n'
        '/second_stage_resources/sheng-remount/67 sheng_overlay_staging_file\n'
        '/second_stage_resources/sheng-remount/68/nested sheng_overlay_staging_file\n')
    host = rom / 'out-clean-ota-20261116/host/linux-x86/bin'
    run(' '.join(shlex.quote(str(x)) for x in
                 (host / 'checkfc', out / 'precompiled_sepolicy', combined_contexts)),
        '04-check-file-contexts')
    run(' '.join(shlex.quote(str(x)) for x in
                 (sys.executable, HERE / 'check_file_context_lookups.py',
                  combined_contexts, expected_contexts)),
        '05-test-file-contexts')
    run(' '.join(shlex.quote(str(x)) for x in
                 (host / 'sefcontext_compile', '-p', out / 'precompiled_sepolicy',
                  '-o', out / 'file_contexts.bin', combined_contexts)),
        '06-compile-file-contexts')
    analyze = rom / 'out-clean-ota-20261116/host/linux-x86/bin/sepolicy-analyze'
    original_permissive = subprocess.check_output([analyze, rom / old_binary, 'permissive'])
    candidate_permissive = subprocess.check_output([analyze, out / 'precompiled_sepolicy', 'permissive'])
    assert candidate_permissive == original_permissive, 'Permissive domain set changed'
    assert b'overlay_remounter' not in candidate_permissive.split(), 'Remounter must remain enforcing'
    assert all(sha(Path(p)) == digest for p, digest in originals.items())
    assert sha(original_contexts) == contexts_hash
    receipt = dict(passed=True, storage_preflight=storage,
                   neverallow_checks_enabled=True, permissive_domains_unchanged=True,
                   overlay_remounter_permissive=False,
                   existing_permissive_domain_count=len(candidate_permissive.split()),
                   policy_source_sha256=sha(owned), original_outputs_unchanged=True,
                   system_ext_cil_sha256=sha(out / 'system_ext_sepolicy.cil'),
                   precompiled_policy_sha256=sha(out / 'precompiled_sepolicy'),
                   file_contexts_source_sha256=sha(contexts),
                   file_contexts_checked=True, file_contexts_lookup_cases=5,
                   original_contexts_unchanged=True,
                   product_integrated=False, runtime_verified=False, flashed=False)
    (out / 'qualification.json').write_text(json.dumps(receipt, indent=2))
    temporary.cleanup()
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
