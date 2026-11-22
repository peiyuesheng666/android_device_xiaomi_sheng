#!/usr/bin/env python3
"""Build the diagnostic launcher using the existing device CLI's compiler ABI."""
from pathlib import Path
import shlex
import subprocess

ROM = Path('/root/sheng-lineage/lineage-24.0')
WORKSPACE = Path('/mnt/c/Users/Dev裴月笙/Desktop/XiaomiPad6SProPort6.18')
WORK = Path('/root/sheng-lineage/hardware-diagnostics/sheng-accessories-r53-20261111/pen-ble-probe')
WORK.mkdir(parents=True, exist_ok=True)
module = 'out/soong/.intermediates/device/xiaomi/sheng/interfaces/input/touch/sheng-touchctl/android_vendor_arm64_armv8-2a-dotprod_kryo'
original = 'device/xiaomi/sheng/interfaces/input/touch/native/TouchControlMain.cpp'
object_path = module+'/obj/'+original.removesuffix('.cpp')+'.o'
binary_path = module+'/unstripped/sheng-touchctl'
def command_for(target):
    lines = subprocess.check_output([ROM/'prebuilts/build-tools/linux-x86/bin/ninja',
        '-f', 'out/combined-lineage_sheng.ninja', '-t', 'commands', target], cwd=ROM, text=True).splitlines()
    line = next(line for line in reversed(lines) if 'clang++' in line and ('-o '+target) in line)
    args = shlex.split(line)
    while args and args[0].startswith('PWD='): args.pop(0)
    assert not any(arg in ['&&', ';', '|'] for arg in args)
    return args
args = command_for(object_path)
args = [str(WORK/'launcher.o') if arg == object_path else str(WORK/'launcher.o.d')
    if arg == object_path+'.d' else str(WORKSPACE/'device/xiaomi/sheng/tools/sheng_pen_probe_launcher.cpp')
    if arg == original else arg for arg in args]
subprocess.run(args, cwd=ROM, check=True)
args = command_for(binary_path)
response = (ROM/(binary_path+'.rsp')).read_text()
assert object_path in response
(WORK/'launcher.rsp').write_text(response.replace(object_path, str(WORK/'launcher.o')))
args = [str(WORK/'sheng-pen-probe') if arg == binary_path else '@'+str(WORK/'launcher.rsp')
    if arg == '@'+binary_path+'.rsp' else arg for arg in args]
subprocess.run(args, cwd=ROM, check=True)
print(WORK/'sheng-pen-probe')
