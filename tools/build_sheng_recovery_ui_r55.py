#!/usr/bin/env python3
"""Compile the device Recovery extension against the installed r54 libraries.

This is a scoped native build. The normal Soong module is defined in the
device tree; the truncated product graph is not used or reported as passing.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import tempfile

DEVICE = Path(__file__).resolve().parents[1]
WORKSPACE = DEVICE.parents[2]
ROM = Path('/root/sheng-lineage/lineage-24.0')
CLANG = ROM / 'prebuilts/clang/host/linux-x86/clang-r547379'
BASE = Path('/root/sheng-lineage/recovery-r54-package-3xcc5ink/root')
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--revision', type=int, choices=(55, 56), default=55)
revision = parser.parse_args().revision
OUT = Path(tempfile.mkdtemp(prefix='recovery-ui-r%d-' % revision, dir='/root/sheng-lineage'))
REVIEW = WORKSPACE / 'reports/device/20261112-recovery-pen'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


source = DEVICE / 'rootdir/recovery/ShengRecoveryUI.cpp'
library = OUT / 'librecovery_ui_ext.so'
deps = BASE / 'system/lib64'
args = [CLANG / 'bin/clang++', '--target=aarch64-linux-android35',
        '--sysroot=' + str(ROM / 'out/soong/ndk/sysroot'),
        '-nostdinc++', '-isystem', CLANG / 'include/c++/v1',
        '-isystem', ROM / 'bootable/recovery/recovery_ui/include',
        '-isystem', ROM / 'bootable/recovery/minui/include',
        '-std=gnu++20', '-O2', '-g', '-fPIC', '-fno-rtti', '-fno-exceptions',
        '-march=armv8.2-a', '-mno-outline-atomics', '-Wall', '-Wextra', '-Werror',
        '-nostdlib', '-shared', '-Wl,--no-undefined',
        '-Wl,-soname,librecovery_ui_ext.so', '-Wl,--build-id=sha1',
        source, '-L', deps, '-lrecovery_ui', '-lc++', '-lc', '-lm', '-ldl',
        CLANG / 'lib/clang/20/lib/linux/libclang_rt.builtins-aarch64-android.a',
        '-o', library]
result = subprocess.run(list(map(str, args)), cwd=ROM, capture_output=True, text=True)
(OUT / 'compile.json').write_text(json.dumps({'command': list(map(str, args)),
    'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}, indent=2) + '\n')
if result.returncode:
    raise RuntimeError(result.stderr)
subprocess.run([CLANG / 'bin/llvm-strip', '--strip-unneeded', library], check=True)
dynamic = subprocess.check_output([CLANG / 'bin/llvm-readelf', '-d', library], text=True)
symbols = subprocess.check_output([CLANG / 'bin/llvm-nm', '-D', library], text=True)
assert ' T make_device' in symbols, 'Recovery factory must remain discoverable'
assert 'librecovery_ui.so' in dynamic and 'libc++.so' in dynamic
assert 'ShengRecoveryUI' in subprocess.check_output([CLANG / 'bin/llvm-strings', library], text=True)
receipt = {
    'revision': revision, 'scope': 'device Recovery UI extension; nonblocking battery reads',
    'full_product_build_passed': False, 'normal_soong_module_build_passed': False,
    'scoped_native_compile_and_no_undefined_link_passed': True,
    'library': str(library), 'sha256': sha(library), 'bytes': library.stat().st_size,
    'sources': {str(path.relative_to(DEVICE)): sha(path) for path in
                (source, DEVICE / 'rootdir/recovery/Android.bp', DEVICE / 'BoardConfig.mk')},
    'headers': {str(path.relative_to(ROM)): sha(path) for path in
                (ROM / 'bootable/recovery/recovery_ui/include/recovery_ui/screen_ui.h',
                 ROM / 'bootable/recovery/recovery_ui/include/recovery_ui/ui.h',
                 ROM / 'bootable/recovery/recovery_ui/include/recovery_ui/device.h')},
    'linked_installed_dependencies': {name: sha(deps / name) for name in
                                    ('librecovery_ui.so', 'libc++.so', 'libc.so', 'libm.so', 'libdl.so')},
    'dynamic': dynamic, 'work': str(OUT), 'hardware_tested': False,
}
(REVIEW / ('r%d-ui-build.json' % revision)).write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2))
