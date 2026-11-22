#!/usr/bin/env python3
"""Compile only DP/display and SuperSpeed PHY against a selected existing kernel."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess

from prepare_sheng_dp_usb import prepare

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--diagnostic-root', type=Path, required=True)
parser.add_argument('--name', default='dp-usb-kernel-20261118')
args = parser.parse_args()
device = Path(__file__).resolve().parents[1]
workspace = device.parents[2]
diagnostic = args.diagnostic_root.resolve()
root = diagnostic / 'vendor-kmi32/k618'
project = diagnostic / 'project-kmi32'
core = (root / 'out-gki').resolve()
deps = diagnostic.parent / 'kernel618-android-deps'
build = diagnostic / ('dp-usb-20261118' if args.name == 'dp-usb-kernel-20261118' else args.name)
build.mkdir(exist_ok=True)
artifact = workspace / 'artifacts' / args.name
artifact.mkdir(parents=True, exist_ok=True)
prepare(root, check=True)
toolchain = deps / 'prebuilts'
clang = toolchain / 'clang/host/linux-x86/clang-r584948c/bin'
hosttools = toolchain / 'kernel-build-tools/linux_musl-x86/bin'
env = dict(os.environ, LANG='C.UTF-8', LC_ALL='C.UTF-8',
           SHENG_REAL_PAHOLE=str(hosttools / 'pahole'),
           KBUILD_GENDWARFKSYMS_STABLE='1', LOCALVERSION='',
           MAKEFLAGS='HOSTCFLAGS=-O2\\ -I' + str(deps / 'elfutils-0.193/include')
           + ' HOSTLDFLAGS=-L' + str(deps / 'elfutils-0.193/lib')
           + '\\ -Wl,-rpath,' + str(deps / 'elfutils-0.193/lib'))
env['PATH'] = ':'.join(map(str, (clang, hosttools,
    toolchain / 'build-tools/linux-x86/bin', toolchain / 'clang-tools/linux-x86/bin')))
env['PATH'] += ':/usr/sbin:/usr/bin:/sbin:/bin'
make = ['make', '-C', root / 'ws/common', 'O=' + str(core), 'ARCH=arm64',
        'LLVM=1', 'LLVM_IAS=1', '-j2', 'JOBS=2',
        'PAHOLE=' + str(project / 'scripts/pahole-memory-gate.py')]
soc = root / 'soc'
tp = root / 'vendor/qcom/opensource'
plan = json.loads((project / 'profiles/techpacks.json').read_text())
display = tp / 'display-drivers'
item = next(item for item in plan['modules'] if item[0] == 'display')
expand = lambda value: value.replace('%M', plan['multimedia_includes']).replace('%T', str(tp)).replace('%D', str(display))
inc = ' -I'.join(expand(item[3]).split())
symbols = [soc / 'Module.symvers']
symbols += [p for p in sorted(tp.rglob('Module.symvers')) if not p.is_relative_to(display)]
jobs = [
    ('display', display, 'msm/msm_drm.ko', [
        'KERNEL_SRC=' + str(root / 'ws/common'), 'KERNEL_ROOT=' + str(root / 'ws/common'),
        'CONFIG_ARCH_KALAMA=y', 'KBUILD_EXTRA_SYMBOLS=' + ' '.join(map(str, symbols)),
        'NOSTDINC_FLAGS=-nostdinc -I' + str(soc / 'include') + ' -I' + str(soc / 'include/uapi') + ' -I' + inc,
        'KCFLAGS=-Wno-error -include ' + str(root / 'tp-autoconf.h') + ' ' + expand(item[4]),
        *shlex.split(expand(item[2]))]),
    ('ssphy', soc, 'phy-msm-ssusb-qmp.ko', []),
]
receipt = dict(compiled=False, installed=False, kernel_release=(core / 'include/config/kernel.release').read_text().strip(), files=[])
for label, stage, target, flags in jobs:
    symvers = stage / 'Module.symvers'
    saved = symvers.read_bytes()
    try:
        with (build / (label + '.log')).open('w') as log:
            command = [*make, 'M=' + str(stage), target, *flags]
            log.write(' '.join(map(shlex.quote, map(str, command))) + '\n')
            log.flush()
            subprocess.run(list(map(str, command)), env=env, check=True, stdout=log, stderr=subprocess.STDOUT)
    finally:
        # A single-module modpost must not replace the full provider export list.
        symvers.write_bytes(saved)
    source = stage / target
    shutil.copyfile(source, artifact / source.name)
    receipt['files'].append(dict(name=source.name, sha256=hashlib.sha256(source.read_bytes()).hexdigest(), bytes=source.stat().st_size))
receipt['compiled'] = True
report_name = 'dp-usb-kernel-build-20261118' if args.name == 'dp-usb-kernel-20261118' else args.name + '-build'
(workspace / 'reports' / (report_name + '.json')).write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2), flush=True)
