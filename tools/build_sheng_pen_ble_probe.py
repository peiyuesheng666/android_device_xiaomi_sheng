#!/usr/bin/env python3
from pathlib import Path
import os
import shutil
import subprocess

ROM = Path('/root/sheng-lineage/lineage-24.0')
SOURCE = Path('/mnt/c/Users/Dev裴月笙/Desktop/XiaomiPad6SProPort6.18/device/xiaomi/sheng')
WORK = Path('/root/sheng-lineage/hardware-diagnostics/sheng-accessories-r53-20261111/pen-ble-probe')
WORK.mkdir(parents=True, exist_ok=True)
os.environ.update(LANG='C.UTF-8', LC_ALL='C.UTF-8', JAVA_HOME=str(ROM/'prebuilts/jdk/jdk21/linux-x86'))
os.environ['PATH'] = os.environ['JAVA_HOME']+'/bin:'+os.environ['PATH']
for path in ['classes', 'dex', 'sources']:
    (WORK/path).mkdir(exist_ok=True)
sources = [SOURCE/'tools'/name for name in (
    'ShengPenBleProbe.java', 'ShengPenGattInspect.java', 'ShengPenPanelObserver.java',
    'ShengPenHidReconnect.java', 'ShengPenInputRestoreProbe.java')]
sources += [SOURCE/'interfaces/input/stylus/src/org/lineageos/sheng/stylus'/name
            for name in ('PenModel.java', 'MippProfile.java')]
copied_sources = []
for source in sources:
    destination = WORK/'sources'/source.name
    shutil.copyfile(source, destination)
    copied_sources.append(destination)
jars = [ROM/'out/soong/.intermediates/frameworks/base/framework-minus-apex/android_common/combined/framework.jar']
bluetooth = ROM/'out/soong/.intermediates/packages/modules/Bluetooth/framework/framework-bluetooth.impl/android_common/combined/framework-bluetooth.jar'
assert bluetooth.is_file()
jars.append(bluetooth)
subprocess.run([ROM/'prebuilts/jdk/jdk21/linux-x86/bin/javac', '-J-Xmx256m', '-source', '8', '-target', '8',
    '-cp', ':'.join(map(str, jars)), '-d', WORK/'classes', *copied_sources], check=True)
subprocess.run([ROM/'prebuilts/jdk/jdk21/linux-x86/bin/jar', 'cf', WORK/'probe.jar', '-C', WORK/'classes', '.'], check=True)
subprocess.run([ROM/'out/host/linux-x86/bin/d8', '--min-api', '35', '--output', WORK/'dex', WORK/'probe.jar'], check=True)
print(WORK/'dex/classes.dex')
