#!/usr/bin/env python3
"""Check candidate module imports/exports against the installed baseline, then sign."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

device = Path(__file__).resolve().parents[1]
workspace = device.parents[2]
sys.path.insert(0, str(workspace / 'scripts'))
from audit_kernel618_modules import ElfModule

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--diagnostic-root', type=Path, required=True)
parser.add_argument('--name', default='dp-usb-kernel-20261118')
args = parser.parse_args()
diagnostic = args.diagnostic_root.resolve()
core = diagnostic / 'out'
k618 = diagnostic / 'vendor-kmi32/k618'
artifacts = workspace / 'artifacts' / args.name
deps = diagnostic.parent / 'kernel618-android-deps'
providers = {}
for path in [core / 'Module.symvers']:
    for line in path.read_text().splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[2] == 'vmlinux':
            crc = int(fields[0], 16)
            if fields[1] in providers:
                assert providers[fields[1]] == crc, fields[1]
            providers[fields[1]] = crc
for path in sorted((diagnostic / 'vendor-kmi32/android-modules/modules').glob('*.ko')):
    for symbol, crc in ElfModule(path).exports().items():
        if symbol in providers:
            assert providers[symbol] == crc, symbol
        providers[symbol] = crc
receipt = {'passed': False, 'installed': False, 'modules': []}
for name in ('msm_drm', 'phy-msm-ssusb-qmp'):
    source = artifacts / (name + '.ko')
    baseline = ElfModule(artifacts / (name + '.before.ko'))
    candidate = ElfModule(source)
    assert baseline.info['vermagic'] == candidate.info['vermagic'], name
    assert baseline.layout_size == candidate.layout_size, name
    assert baseline.exports() == candidate.exports(), 'Exported ABI changed: ' + name
    mismatches = {symbol: [crc, providers.get(symbol)] for symbol, crc in candidate.versions().items()
                  if providers.get(symbol) != crc}
    assert not mismatches, mismatches
    assert candidate.undefined() <= set(providers), candidate.undefined() - set(providers)
    signed = artifacts / (name + '.signed.ko')
    shutil.copyfile(source, signed)
    subprocess.run([str(deps / 'prebuilts/clang/host/linux-x86/clang-r584948c/bin/llvm-strip'),
                    '--strip-debug', str(signed)], check=True)
    subprocess.run([str(core / 'scripts/sign-file'), 'sha256', str(core / 'certs/signing_key.pem'),
                    str(core / 'certs/signing_key.x509'), str(signed)], check=True)
    # Sign with the exact certificate already embedded in the selected kernel.
    assert (core / 'certs/signing_key.x509').read_bytes() in (core / 'certs/system_certificates.o').read_bytes()
    subprocess.run([str(diagnostic / 'vendor-kmi32/qualified/host/btf-verify'), 'verify',
                    str(core / 'kernel-module-base.btf'), str(signed)], check=True)
    receipt['modules'].append({'name': name, 'imports_checked': len(candidate.versions()),
                              'exports_unchanged': True, 'btf_verified': True,
                              'signed_sha256': hashlib.sha256(signed.read_bytes()).hexdigest(),
                              'signed_bytes': signed.stat().st_size})
receipt['passed'] = True
report_name = 'dp-usb-kernel-qualification-20261118' if args.name == 'dp-usb-kernel-20261118' else args.name + '-qualification'
(workspace / 'reports' / (report_name + '.json')).write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2))
