#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compile proposed stylus split-policy inputs against the sealed r64 baseline."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
rom = Path('/root/sheng-lineage/lineage-24.0')
product = rom/'out/target/product/sheng'
baseline = json.loads(args.baseline.read_text())
assert baseline['revision'] == 64 and baseline['complete_avb_chain_verified']
original = Path(baseline['work_dir'])
prior = baseline['boot_policy']['input_sha256']
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
assert prior and all(sha(original/name) == digest for name, digest in prior.items())
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=False)
receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), passed=False,
    baseline_sha256=sha(args.baseline), baseline_inputs_verified=True,
    normal_module_build_qualified=False, installed=False, hardware_tested=False, attempts=[])
prefixes = {
    'system_ext': 'system_ext-after/etc/selinux/',
    'vendor': 'vendor-tree/etc/selinux/',
    'product': 'product-policy/selinux/',
    'system': 'system-policy/selinux/',
}
try:
    for partitions in [('system_ext', 'vendor'), ('system_ext', 'vendor', 'product'),
                       ('system_ext', 'vendor', 'product', 'system')]:
        inputs = []
        replacements = {}
        for name in prior:
            selected = original/name
            for part in partitions:
                if name.startswith(prefixes[part]):
                    selected = product/part/'etc/selinux'/name.removeprefix(prefixes[part])
                    replacements[name] = str(selected)
                    break
            assert selected.is_file(), selected
            inputs.append(selected)
        hashes = {str(path): sha(path) for path in inputs}
        label = '-'.join(partitions)
        command = [rom/'out/host/linux-x86/bin/secilc', inputs[0], '-m', '-M', 'true',
                   '-G', '-c', '30', *inputs[1:], '-o', output/(label+'.policy'), '-f', '/dev/null']
        result = subprocess.run(list(map(str, command)), text=True, capture_output=True, timeout=180)
        (output/(label+'.log')).write_text(result.stdout+result.stderr)
        stable = all(sha(Path(name)) == digest for name, digest in hashes.items())
        receipt['attempts'].append(dict(partitions=list(partitions), argv=list(map(str, command)),
            exit_code=result.returncode, inputs_sha256=hashes, inputs_stable=stable,
            replacements=replacements, neverallows_enabled=True))
        if not stable: raise RuntimeError('Policy inputs changed during the diagnostic')
        if result.returncode == 0:
            receipt.update(passed=True, required_policy_partitions=list(partitions),
                           actual_mixed_policy_neverallows_passed=True)
            break
    if not receipt['passed']: raise RuntimeError('No proposed split-policy combination compiled')
finally:
    (output/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
print(json.dumps(dict(passed=receipt['passed'], required_policy_partitions=receipt.get('required_policy_partitions'))))
