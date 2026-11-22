#!/usr/bin/env python3
"""Use the already compiled sheng CLI flags for a bounded diagnostic only."""
from pathlib import Path
import shlex
import subprocess

rom = Path('/root/sheng-lineage/lineage-24.0')
workspace = Path('/mnt/c/Users/Dev裴月笙/Desktop/XiaomiPad6SProPort6.18')
work = Path('/root/sheng-lineage/hardware-diagnostics/sheng-bt-touch-r48-20261111/sampling-probe')
work.mkdir(exist_ok=True)
assert not (work/'sheng-touch-sampling-probe').exists()
module = 'out/soong/.intermediates/device/xiaomi/sheng/interfaces/input/touch/sheng-touchctl/android_vendor_arm64_armv8-2a-dotprod_kryo'
original = 'device/xiaomi/sheng/interfaces/input/touch/native/TouchControlMain.cpp'
object_path = module + '/obj/' + original.removesuffix('.cpp') + '.o'
binary_path = module + '/unstripped/sheng-touchctl'
ninja = rom/'prebuilts/build-tools/linux-x86/bin/ninja'

def command_for(target):
    lines = subprocess.check_output([ninja, '-f', 'out/combined-lineage_sheng.ninja',
                                     '-t', 'commands', target], cwd=rom, text=True).splitlines()
    line = next(line for line in reversed(lines) if 'clang++' in line and ('-o ' + target) in line)
    args = shlex.split(line)
    while args and args[0].startswith('PWD='):
        args.pop(0)
    assert not any(arg in ['&&', ';', '|'] for arg in args)
    return args

compile_args = command_for(object_path)
compile_args = [str(work/'probe.o') if arg == object_path else
                str(work/'probe.o.d') if arg == object_path+'.d' else
                str(workspace/'device/xiaomi/sheng/tools/sheng_touch_sampling_probe.cpp')
                if arg == original else arg for arg in compile_args]
subprocess.run(compile_args, cwd=rom, check=True)
link_args = command_for(binary_path)
response = (rom/(binary_path+'.rsp')).read_text()
assert object_path in response
response = response.replace(object_path, str(work/'probe.o'))
(work/'probe.rsp').write_text(response)
link_args = [str(work/'sheng-touch-sampling-probe') if arg == binary_path else
             '@'+str(work/'probe.rsp') if arg == '@'+binary_path+'.rsp' else arg for arg in link_args]
subprocess.run(link_args, cwd=rom, check=True)
print(work/'sheng-touch-sampling-probe')
