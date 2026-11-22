#!/usr/bin/env python3
"""Build an isolated DP diagnostic module from a retained matching kernel build.

Never installs or flashes. The retained display tree and module are not modified.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline-out', type=Path, required=True)
    p.add_argument('--dependencies', type=Path, required=True)
    p.add_argument('--work-dir', type=Path, required=True)
    p.add_argument('--patch', type=Path, required=True)
    p.add_argument('--jobs', type=int, choices=(1, 2), default=1)
    a = p.parse_args()
    base, deps, work = (x.resolve() for x in
                        (a.baseline_out, a.dependencies, a.work_dir))
    if os.name != 'posix' or any(str(x).startswith('/mnt/') for x in (base, deps, work)):
        p.error('Use native C-backed WSL paths, not Windows mounts.')
    if work.exists() or work == base or base in work.parents or work in base.parents:
        p.error('work-dir must be a new directory outside the baseline.')
    k = base / 'SHENG_VENDOR_KERNEL_OBJ/k618'
    core = base / 'core'
    project = base / 'SHENG_KERNEL_PROJECT'
    tp = k / 'vendor/qcom/opensource'
    original = tp / 'display-drivers'
    module = original / 'msm/msm_drm.ko'
    anchors = [module, core / 'kernel-Image', core / 'Module.symvers', core / '.config',
               original / 'msm/dp/dp_panel.c', original / 'msm/dp/dp_display.c']
    before = {str(x): sha(x) for x in anchors}
    if shutil.disk_usage(work.parent).free < 3 * 1024**3:
        p.error('Less than 3 GiB free; do not start the trial build.')
    work.mkdir()
    receipt = dict(compiled=False, installed=False, flashed=False,
                   kernel_release=(core / 'include/config/kernel.release').read_text().strip(),
                   baseline=before, patch_sha256=sha(a.patch))
    try:
        display = work / 'display-drivers'
        shutil.copytree(original, display, symlinks=True)
        subprocess.run(['git', 'apply', '--check', str(a.patch.resolve())], cwd=display, check=True)
        subprocess.run(['git', 'apply', str(a.patch.resolve())], cwd=display, check=True)
        plan = json.loads((project / 'profiles/techpacks.json').read_text())
        item = next(x for x in plan['modules'] if x[0] == 'display')

        def expand(value):
            for key, replacement in [('%M', plan['multimedia_includes']), ('%T', str(tp)),
                                     ('%D', str(display)), ('%P', str(display.parent))]:
                value = value.replace(key, replacement)
            return value

        symbols = [k / 'soc/Module.symvers', k / 'sheng-ports/pogo/Module.symvers']
        for entry in plan['modules']:
            if entry[0] == 'display':
                break
            symbols.append(tp / entry[1] / 'Module.symvers')
        for path in symbols:
            if not path.is_file():
                raise FileNotFoundError(path)
        pre = deps / 'prebuilts'
        clang = pre / 'clang/host/linux-x86/clang-r584948c/bin'
        host = pre / 'kernel-build-tools/linux_musl-x86/bin'
        elf = deps / 'elfutils-0.193'
        env = dict(os.environ, LANG='C.UTF-8', LC_ALL='C.UTF-8',
                   KBUILD_GENDWARFKSYMS_STABLE='1', LOCALVERSION='',
                   SHENG_REAL_PAHOLE=str(host / 'pahole'),
                   KBUILD_BUILD_USER='peiyuesheng', KBUILD_BUILD_HOST='MiFans', KBUILD_BUILD_VERSION='1',
                   MAKEFLAGS=f'HOSTCFLAGS=-O2\\ -I{elf}/include HOSTLDFLAGS=-L{elf}/lib\\ -Wl,-rpath,{elf}/lib')
        env['PATH'] = ':'.join(map(str, [clang, host, pre / 'build-tools/linux-x86/bin',
                                       pre / 'clang-tools/linux-x86/bin'])) + ':/usr/bin:/bin'
        includes = [str(k / 'soc/include'), str(k / 'soc/include/uapi'), *expand(item[3]).split()]
        command = ['make', '-C', str(k / 'ws/common'), f'O={core}', 'ARCH=arm64',
                   'LLVM=1', 'LLVM_IAS=1', f'-j{a.jobs}', f'JOBS={a.jobs}',
                   f'PAHOLE={project}/scripts/pahole-memory-gate.py', f'M={display}',
                   'msm/msm_drm.ko', 'CONFIG_ARCH_KALAMA=y', f'KERNEL_SRC={k}/ws/common',
                   f'KERNEL_ROOT={k}/ws/common', 'KBUILD_EXTRA_SYMBOLS=' + ' '.join(map(str, symbols)),
                   'NOSTDINC_FLAGS=-nostdinc -I' + ' -I'.join(includes),
                   f'KCFLAGS=-Wno-error -include {k}/tp-autoconf.h ' + expand(item[4]),
                   *shlex.split(expand(item[2]))]
        receipt['command'] = command
        with (work / 'build.log').open('w') as log:
            log.write(shlex.join(command) + '\n')
            log.flush()
            subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        result = display / 'msm/msm_drm.ko'
        receipt.update(compiled=True, module=str(result), sha256=sha(result))
    finally:
        receipt['baseline_unchanged'] = all(sha(Path(x)) == digest for x, digest in before.items())
        (work / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        if not receipt['baseline_unchanged']:
            raise RuntimeError('Retained baseline changed; do not deploy candidate.')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
