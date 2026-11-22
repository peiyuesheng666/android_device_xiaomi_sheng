#!/usr/bin/env python3
"""Build the device-owned compositor candidate using the existing ROM objects."""
import hashlib
import argparse
import json
import os
import shlex
from pathlib import Path
import subprocess

workspace = Path(__file__).resolve().parents[4]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--name', default='translucent-composition-20261118')
args = parser.parse_args()
if not args.name or Path(args.name).name != args.name:
    parser.error('--name must be a single directory name')
rom = Path('/root/sheng-pixelos/android')
out = Path('out-clean-ota-20261116')
report = workspace / 'reports' / args.name
report.mkdir(parents=True, exist_ok=True)
artifact = workspace / 'artifacts' / args.name
artifact.mkdir(parents=True, exist_ok=True)
diagnostic = rom.parent / 'diagnostics' / args.name
diagnostic.mkdir(parents=True, exist_ok=True)
relative = Path('device/xiaomi/sheng/interfaces/display/composer')
for name in ('hwc_display.cpp', 'client_composition_range.h'):
    (rom / relative / name).write_bytes((workspace / relative / name).read_bytes())
test = workspace / 'device/xiaomi/sheng/tools/test_client_composition_range.cpp'
binary = diagnostic / 'composition-test'
subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-g', str(test), '-o', str(binary)], check=True)
subprocess.run([str(binary)], check=True)
module = 'vendor.qti.hardware.display.composer-service-sheng'
base = out / 'soong/.intermediates' / relative / module
target = base / 'android_vendor_arm64_armv8-2a-dotprod_kryo/unstripped' / module
commands = subprocess.check_output([
    str(rom / 'prebuilts/build-tools/linux-x86/bin/ninja'), '-f',
    str(out / 'combined-custom_sheng.ninja'), '-t', 'commands', str(target)
], cwd=rom, text=True).splitlines()
compiles = [c for c in commands if str(relative / 'hwc_display.cpp') in c and '/obj/' in c]
links = [c for c in commands if ' -o ' + str(target) + ' ' in c]
assert len(compiles) == len(links) == 1, (len(compiles), len(links))
for label, command in [('compile', compiles[0]), ('link', links[0])]:
    print(label, flush=True)
    (diagnostic / (label + '.command')).write_text(command + '\n')
    with (diagnostic / (label + '.log')).open('w') as log:
        subprocess.run(command, cwd=rom, shell=True, executable='/bin/bash',
                       env=dict(os.environ, LANG='C.UTF-8', LC_ALL='C.UTF-8'),
                       stdout=log, stderr=subprocess.STDOUT, check=True)
candidate = artifact / module
compiler = next(p for p in shlex.split(compiles[0]) if p.endswith('/bin/clang++'))
subprocess.run([str(rom / Path(compiler).with_name('llvm-strip')),
                '--strip-all', '-o', str(candidate), str(rom / target)], check=True)
result = dict(compiled=True, host_sanitizers_passed=True,
              sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
              candidate=str(candidate), installed=False)
(report / 'candidate-build.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2), flush=True)
