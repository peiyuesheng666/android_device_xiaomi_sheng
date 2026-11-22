#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compile the APE extractor against existing platform libraries without Soong."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, default='/root/sheng-lineage/lineage-24.0')
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    rom = args.rom.resolve(strict=True)
    device = Path(__file__).resolve().parents[1]
    src = device / 'interfaces/media/ape'
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    assert work.stat().st_dev == Path('/').stat().st_dev, 'Use native C-backed storage'
    variant = 'android_arm64_armv8-2a-dotprod_kryo'
    clang = Path('prebuilts/clang/host/linux-x86/clang-r596125')
    compiler = clang / 'bin/clang++'
    library_rsp = rom / ('out/soong/.intermediates/frameworks/av/media/module/extractors/amr/'
                        'libamrextractor/' + variant + '_shared_cfi_apex31/unstripped/libamrextractor.so.rsp')
    libraries = [Path(p) for p in shlex.split(library_rsp.read_text()) if p.endswith('.so')]
    assert {p.name for p in libraries} == {'liblog.so', 'libmediandk.so', 'libc++.so',
                                         'libc.so', 'libm.so', 'libdl.so'}
    libraries = [Path(str(p).replace(variant + '_shared_apex31', variant + '_shared'))
                 if p.name == 'libc++.so' else p for p in libraries]
    builtins = clang / 'lib/clang/22/lib/linux/libclang_rt.builtins-aarch64-android.a'
    inputs = [rom / compiler, rom / builtins, library_rsp, *[rom / p for p in libraries]]
    cflags = ['-target', 'aarch64-linux-android29', '-std=c++20', '-O2', '-g', '-nostdlibinc',
              '-DANDROID', '-DNDEBUG', '-D_FORTIFY_SOURCE=3', '-D__ANDROID_UNAVAILABLE_SYMBOLS_ARE_WEAK__',
              '-fno-exceptions', '-fno-rtti', '-fno-strict-aliasing', '-fstack-protector-strong',
              '-ffunction-sections', '-fdata-sections', '-fvisibility=hidden', '-Wall', '-Wextra', '-Werror',
              '-fsanitize=unsigned-integer-overflow,signed-integer-overflow', '-fsanitize-trap=all']
    include_dirs = [src, 'frameworks/av/include', 'frameworks/av/media/ndk/include',
                    'frameworks/native/libs/nativewindow/include', 'frameworks/native/libs/arect/include',
                    'system/core/libutils/include', 'system/core/libutils/binder/include',
                    'system/logging/liblog/include', 'system/core/libcutils/include',
                    clang / 'android_libc++/platform/aarch64/include/c++/v1', clang / 'include/c++/v1']
    cflags += ['-I' + str(p) for p in include_dirs]
    for path in ['bionic/libc/include', 'bionic/libc/kernel/uapi/asm-arm64', 'bionic/libc/kernel/uapi',
                 'bionic/libc/kernel/android/scsi', 'bionic/libc/kernel/android/uapi']:
        cflags += ['-isystem', path]
    ldflags = ['-target', 'aarch64-linux-android29', '-fuse-ld=lld', '-nostdlib',
               '-Wl,--no-undefined', '-Wl,--fatal-warnings', '-Wl,--gc-sections',
               '-Wl,-z,noexecstack', '-Wl,-z,relro', '-Wl,-z,now', '-Wl,-z,max-page-size=16384',
               '-Wl,--build-id=sha1', '-Wl,--threads=1', '-Wl,--exclude-libs,ALL']
    env = dict(os.environ, LANG='C.UTF-8', LC_ALL='C.UTF-8', TMPDIR=str(work))
    env.pop('LD_LIBRARY_PATH', None)
    commands, outputs = [], {}

    def run(command, name):
        command = list(map(str, command))
        commands.append(command)
        result = subprocess.run(command, cwd=rom, env=env, text=True, capture_output=True, timeout=90)
        (work / (name + '.log')).write_text(result.stdout + result.stderr)
        if result.returncode:
            print(result.stdout + result.stderr)
        result.check_returncode()

    sources = [src / p for p in ('ApeFile.h', 'ShengApeExtractor.cpp', 'Android.bp', 'exports.map')]
    sources += [device / 'tools/ShengApeExtractorProbe.cpp', Path(__file__).resolve()]
    source_hashes = {str(p.relative_to(device)): sha(p) for p in sources}
    for name, source, shared in [('libshengapeextractor.so', src / 'ShengApeExtractor.cpp', True),
                                 ('sheng-ape-extractor-probe', device / 'tools/ShengApeExtractorProbe.cpp', False)]:
        obj = work / (name + '.o')
        run([compiler, *cflags, '-fPIC' if shared else '-fPIE', '-MMD', '-MF', work / (name + '.d'),
             '-c', source, '-o', obj], name + '-compile')
        begin = 'crtbegin_so' if shared else 'crtbegin_dynamic'
        end = 'crtend_so' if shared else 'crtend_android'
        crt = [Path(f'out/soong/.intermediates/bionic/libc/{n}/{variant}/{n}.o') for n in (begin, end)]
        inputs.extend(rom / p for p in crt)
        flags = ['-shared', '-Wl,-soname,' + name, '-Wl,--version-script=' + str(src / 'exports.map')]
        if not shared:
            flags = ['-pie', '-Wl,-dynamic-linker,/system/bin/linker64']
        output = work / name
        run([compiler, *ldflags, *flags, crt[0], obj, builtins, *libraries, crt[1], '-o', output], name + '-link')
        run([clang / 'bin/llvm-readelf', '-h', '-d', '-l', '--dyn-syms', output], name + '-elf')
        outputs[name] = dict(path=str(output), sha256=sha(output), bytes=output.stat().st_size)
    assert source_hashes == {str(p.relative_to(device)): sha(p) for p in sources}
    record = dict(date_utc=datetime.now(timezone.utc).isoformat(), passed=True,
                  targeted_module_build_passed=True, normal_module_build_passed=False,
                  ninja_graph_loaded=False, source_sha256=source_hashes,
                  input_sha256={str(p): sha(p) for p in sorted(set(inputs))},
                  outputs=outputs, commands=commands)
    (work / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(dict(passed=True, build=str(work / 'build.json'))))


if __name__ == '__main__':
    main()
