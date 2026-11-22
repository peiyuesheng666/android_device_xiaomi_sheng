#!/usr/bin/env python3
"""Build, qualify and persist a diagnostic in one WSL lifetime; never flash.

Large link intermediates live in RAM, not the space-constrained host VHD.
Only images, exact sources, objects and receipts are retained on the host.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[4] / 'scripts'))
from storage_guard import require_build_space
from audit_kernel618_modules import ElfModule


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('parent', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    parent = args.parent.resolve(strict=True)
    output = args.output.resolve()
    require_build_space(output)
    require_build_space('/dev/shm', minimum_output=3 * 1024**3)
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='sheng-busytrace-', dir='/dev/shm') as temp:
        trial = Path(temp) / 'trial'
        try:
            subprocess.run([sys.executable, HERE / 'build_kernel_busy_trace.py', parent, trial], check=True)
            kernel = trial / 'linked/kernel'
            clang = Path('/root/sheng-pixelos/diagnostics/kernel618-android-deps/prebuilts/clang/host/linux-x86/clang-r584948c/bin')
            verifier = Path('/root/sheng-pixelos/diagnostics/ksu-rawdump-20261117/vendor-kmi32/qualified/host/btf-verify')
            btf = trial / 'kernel.btf'
            subprocess.run([clang / 'llvm-objcopy', '--dump-section', '.BTF=' + str(btf), kernel / 'vmlinux', '/dev/null'], check=True)
            modules = [ElfModule(p) for p in sorted((parent / 'modules').glob('*.ko'))]
            assert len(modules) == 343
            providers = defaultdict(list)
            for line in (kernel / 'vmlinux.symvers').read_text().splitlines():
                fields = line.split()
                assert fields[2] == 'vmlinux'
                providers[fields[1]].append(('vmlinux', int(fields[0], 16)))
            for module in modules:
                for symbol, crc in module.exports().items():
                    providers[symbol].append((module.path.name, crc))
            rows, details = [], []
            for module in modules:
                versions = module.versions()
                assert 'module_layout' in versions, module.path
                errors = {symbol: providers.get(symbol, []) for symbol, crc in versions.items()
                          if len(providers.get(symbol, [])) != 1 or providers[symbol][0][1] != crc}
                assert not errors, (module.path, errors)
                p = subprocess.run([verifier, 'verify', btf, module.path], capture_output=True, text=True)
                rows.append(dict(module=module.path.name, returncode=p.returncode, stdout=p.stdout, stderr=p.stderr))
                details.append(dict(module=module.path.name, sha256=module.digest,
                                    versioned_imports=len(versions), crc_passed=True, btf_passed=p.returncode == 0))
                assert p.returncode == 0, (module.path, p.stderr)
                if len(rows) % 50 == 0:
                    print('Modules qualified:', len(rows), flush=True)
            (trial / 'module-btf-crc-check.json').write_text(json.dumps(rows, indent=2))
            (trial / 'module-qualification-details.json').write_text(json.dumps(dict(
                passed=True, modules=details, kernel_btf_sha256=sha(btf),
                verifier_sha256=sha(verifier)), indent=2))
            subprocess.run([sys.executable, HERE / 'package_trial.py', trial, trial / 'package'], check=True)
            # The paired userspace images must be identical to the installed trial.
            expected = {'vendor_boot': '6f8435b471d71cd642997068c9aa746fd0d64ba547a15c54f7547139401c57a1',
                        'init_boot': '2c972aa0914db8f8715c999f270a33e53428b957e00b94b80be17c252c69e40f'}
            for name, digest in expected.items():
                assert sha(trial / 'package/images' / (name + '.img')) == digest, name
            for rel in ('objects/kernel', 'linked', 'package'):
                source = trial / rel
                dest = output / rel
                dest.mkdir(parents=True)
                for path in source.rglob('*'):
                    if path.is_symlink() or not path.is_file():
                        continue
                    relative = path.relative_to(source)
                    keep = path.suffix in ('.json', '.stdout', '.stderr', '.ninja', '.c', '.d')
                    keep |= rel == 'objects/kernel'
                    keep |= rel == 'package' and relative.parts[0] == 'images'
                    keep |= str(relative) in ('kernel/Image', 'kernel/vmlinux.symvers', 'kernel/.config', 'init')
                    if keep:
                        target = dest / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(path, target)
            for path in trial.glob('*'):
                if path.is_file():
                    shutil.copy2(path, output / path.name)
            receipts = {str(p.relative_to(output)): sha(p) for p in output.rglob('*') if p.is_file()}
            (output / 'manifest.json').write_text(json.dumps(dict(
                status='offline_diagnostic_qualified_not_flashed', files=receipts,
                module_count=343, paired_userspace_images_identical=True,
                runtime_verified=False, flashed=False), indent=2))
            print('Persisted offline qualified diagnostic:', output, flush=True)
        except Exception:
            # Keep small failure receipts even though RAM is released below.
            for path in trial.rglob('*'):
                if path.is_file() and not path.is_symlink() and path.suffix in ('.json', '.stdout', '.stderr'):
                    dest = output / 'failure' / path.relative_to(trial)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, dest)
            raise


if __name__ == '__main__':
    main()
