#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compile and run an isolated vendor display capability query without Soong."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--capabilities', action='store_true')
    args = parser.parse_args()
    rom = Path('/root/sheng-lineage/lineage-24.0')
    tools = Path(__file__).resolve().parent
    workspace = tools.parents[3]
    work, output = args.work.resolve(), args.output.resolve()
    work.mkdir(parents=True, exist_ok=False)
    assert work.stat().st_dev == Path('/').stat().st_dev
    output.mkdir(parents=True, exist_ok=False)
    source = tools / 'ShengDisplayLibraryProbe.c'
    clang = rom / 'prebuilts/clang/host/linux-x86/clang-r596125'
    variant = 'android_arm64_armv8-2a-dotprod_kryo'
    crt = [rom / f'out/soong/.intermediates/bionic/libc/{n}/{variant}/{n}.o'
           for n in ('crtbegin_dynamic', 'crtend_android')]
    prior = json.loads((Path('/root/sheng-lineage/hardware-diagnostics/ape-extractor-build/build.json')).read_text())
    libraries = [Path(p) for p in prior['input_sha256'] if Path(p).name in ('libc.so', 'libdl.so')]
    assert len(libraries) == 2
    executable = work / 'sheng-display-library-probe'
    includes = []
    for path in ['bionic/libc/include', 'bionic/libc/kernel/uapi/asm-arm64', 'bionic/libc/kernel/uapi',
                 'bionic/libc/kernel/android/scsi', 'bionic/libc/kernel/android/uapi']:
        includes += ['-isystem', str(rom / path)]
    command = [str(clang / 'bin/clang'), '-target', 'aarch64-linux-android29', '-std=c11',
               '-O2', '-g', '-DANDROID', '-fPIE', '-fstack-protector-strong', '-D_FORTIFY_SOURCE=3',
               '-Wall', '-Wextra', '-Werror', '-nostdlibinc', *includes,
               '-fuse-ld=lld', '-nostdlib', '-pie', '-Wl,-dynamic-linker,/system/bin/linker64',
               '-Wl,--no-undefined', '-Wl,-z,relro', '-Wl,-z,now', '-Wl,-z,noexecstack',
               '-Wl,--threads=1', str(crt[0]), str(source), *map(str, libraries),
               str(clang / 'lib/clang/22/lib/linux/libclang_rt.builtins-aarch64-android.a'),
               str(crt[1]), '-o', str(executable)]
    env = dict(os.environ, TMPDIR=str(work))
    env.pop('LD_LIBRARY_PATH', None)
    result = subprocess.run(command, env=env, capture_output=True, timeout=60)
    (work / 'build.log').write_bytes(result.stdout + result.stderr)
    if result.returncode:
        print((result.stdout + result.stderr).decode(errors='replace'))
    result.check_returncode()
    build = dict(passed=True, source_sha256=sha(source), executable_sha256=sha(executable),
                 command=command, ninja_graph_loaded=False)
    (work / 'build.json').write_text(json.dumps(build, indent=2) + '\n')
    shutil.copyfile(executable, output / executable.name)
    shutil.copyfile(work / 'build.json', output / 'build.json')
    remote = '/data/local/tmp/sheng-display-libraries-' + uuid.uuid4().hex[:12]
    adb = workspace / 'tools/platform-tools/adb.exe'
    receipt = dict(inspection_completed=False, started_utc=datetime.now(timezone.utc).isoformat(),
                   source_sha256=sha(source), executable_sha256=sha(executable), commands=[],
                   display_surface_used=False, camera_used=False, screenshot_taken=False)

    def call(label, *arguments):
        result = subprocess.run([str(adb), '-s', 'ca10ede3', *arguments], capture_output=True, timeout=35)
        (output / (label + '.stdout')).write_bytes(result.stdout)
        (output / (label + '.stderr')).write_bytes(result.stderr)
        receipt['commands'].append(dict(label=label, arguments=arguments, returncode=result.returncode))
        result.check_returncode()
        return result.stdout.decode(errors='replace').strip()

    def state(label):
        return call(label, 'shell', 'cat /proc/sys/kernel/random/boot_id; pidof android.hardware.graphics.composer@2.4-service surfaceflinger; getenforce')

    created = False
    try:
        receipt['before'] = state('before')
        call('mkdir', 'shell', 'test ! -e ' + remote + ' && mkdir -m 0700 ' + remote)
        created = True
        local = subprocess.check_output(['wslpath', '-w', str(output / executable.name)], text=True).strip()
        call('push', 'push', local, remote + '/probe')
        assert call('hash', 'shell', 'sha256sum ' + remote + '/probe').split()[0] == sha(executable)
        call('mode', 'shell', 'chmod 0500 ' + remote + '/probe')
        call('libraries', 'shell', 'sha256sum /vendor/lib64/libsdmextension.so /vendor/lib64/libhdr_tm.so')
        mode = '--inspect-capabilities' if args.capabilities else '--inspect-libraries'
        text = call('probe', 'shell', 'LD_LIBRARY_PATH=/vendor/lib64 timeout 20 ' + remote + '/probe ' + mode)
        print(text, flush=True)
        receipt['inspection_completed'] = True
    except BaseException as error:
        receipt.update(inspection_completed=False, error=repr(error))
    finally:
        try:
            receipt['after'] = state('after')
            assert receipt['after'] == receipt['before']
            receipt['display_services_and_boot_unchanged'] = True
            call('diagnostics', 'logcat', '-b', 'all', '-d', '-v', 'threadtime', '-s', 'SDM:*', 'TMC:*', 'HDR:*')
        except BaseException as error:
            receipt.update(inspection_completed=False, state_error=repr(error))
        if created:
            try:
                call('cleanup', 'shell', 'rm -f ' + remote + '/probe && rmdir ' + remote)
                receipt['temporary_files_removed'] = True
            except BaseException as error:
                receipt.update(inspection_completed=False, cleanup_error=repr(error))
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    if not receipt['inspection_completed']:
        print(json.dumps(dict(error=receipt.get('error'), report=str(output / 'receipt.json'))))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
