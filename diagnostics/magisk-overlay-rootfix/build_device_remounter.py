#!/usr/bin/env python3
"""Compile sheng-owned remounter or syscall test with retained Android edges.

No public source/output replacement, product integration, or device access.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / 'tools'))
from build_sheng_fstab_variants import blocks, statements
from storage_guard import require_build_space


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rom', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--test-only', action='store_true')
    args = parser.parse_args()
    rom, out = args.rom.resolve(strict=True), args.out.resolve()
    require_build_space(out)
    out.mkdir(parents=True, exist_ok=False)
    original = rom / 'system/core/overlay_remounter/overlay_remounter.cpp'
    original_hash = sha(original)
    owned = HERE.parents[1] / 'interfaces/compat/overlay-remounter'
    source = owned / ('mount_preserver_test.cpp' if args.test_only else 'overlay_remounter.cpp')
    candidate = out / source.name
    shutil.copy2(source, candidate)
    shutil.copy2(owned / 'mount_preserver.h', out / 'mount_preserver.h')
    soong = rom / 'out-clean-ota-20261116/soong'
    main_graph = soong / 'build.custom_sheng.ninja'
    definitions = [s for s in statements(main_graph) if s.startswith('g.') and ' = ' in s]
    rules = [b for b in blocks(main_graph) if b[0] in ('rule g.cc.cc', 'rule g.cc.ld')]
    edges = [b for b in blocks(soong / 'build.custom_sheng.8.ninja')
             if b[0].startswith('build ') and '/overlay_remounter/' in b[0]
             and (': g.cc.cc ' in b[0] or ': g.cc.ld ' in b[0])]
    assert len(rules) == len(edges) == 2
    cc = next(b for b in edges if ': g.cc.cc ' in b[0])
    ld = next(b for b in edges if ': g.cc.ld ' in b[0])
    obj = cc[0][6:].split(': ', 1)[0]
    binary = ld[0][6:].split(': ', 1)[0]
    new_obj, new_bin = out / 'candidate.o', out / 'candidate.unstripped'
    cc = [s.replace(obj, str(new_obj)).replace(str(original.relative_to(rom)), str(candidate)) for s in cc]
    ld = [s.replace(binary, str(new_bin)).replace(obj, str(new_obj)) for s in ld]
    graph = out / 'candidate.ninja'
    graph.write_text('\n'.join(definitions + ['builddir = ' + str(out)] +
                               ['\n'.join(b) for b in rules + [cc, ld]]) + '\n')
    command = [rom / 'prebuilts/build-tools/linux-x86/bin/ninja', '-f', graph, '-j1', '-v', new_bin]
    p = subprocess.run(command, cwd=rom, capture_output=True)
    (out / 'build.stdout').write_bytes(p.stdout)
    (out / 'build.stderr').write_bytes(p.stderr)
    assert p.returncode == 0, p.stderr.decode(errors='replace')
    result = out / ('mount-preserver-test' if args.test_only else 'overlay_remounter')
    subprocess.run([rom / 'prebuilts/clang/host/linux-x86/clang-r596125/bin/llvm-strip',
                    '--strip-debug', '-o', result, new_bin], check=True)
    assert sha(original) == original_hash
    receipt = dict(passed=True, test_only=args.test_only, binary_sha256=sha(result),
                   source_sha256=sha(candidate), header_sha256=sha(out / 'mount_preserver.h'),
                   original_source_sha256=original_hash, original_source_unchanged=True,
                   product_integrated=False, android_selinux_verified=False, device_access=False)
    (out / 'qualification.json').write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
