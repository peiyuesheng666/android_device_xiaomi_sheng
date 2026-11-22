#!/usr/bin/env python3
"""Compile a bounded input-policy probe against this ROM's existing framework ABI."""
from pathlib import Path
import os
import shutil
import subprocess

os.environ.update(LANG='C.UTF-8', LC_ALL='C.UTF-8')

ROM = Path('/root/sheng-lineage/lineage-24.0')
os.environ['JAVA_HOME'] = str(ROM/'prebuilts/jdk/jdk21/linux-x86')
os.environ['PATH'] = os.environ['JAVA_HOME'] + '/bin:' + os.environ['PATH']
SOURCE = Path('/mnt/c/Users/Dev裴月笙/Desktop/XiaomiPad6SProPort6.18/device/xiaomi/sheng')
WORK = Path('/root/sheng-lineage/hardware-diagnostics/sheng-accessories-r53-20261111/probe')
WORK.mkdir(parents=True, exist_ok=True)
(WORK/'classes').mkdir(exist_ok=True)
(WORK/'dex').mkdir(exist_ok=True)
framework = ROM/'out/soong/.intermediates/frameworks/base/framework-minus-apex/android_common/combined/framework.jar'
shutil.copyfile(SOURCE/'interfaces/input/keyboard/KeyboardPresenceProbe.java', WORK/'KeyboardPresenceProbe.java')
subprocess.run([ROM/'prebuilts/jdk/jdk21/linux-x86/bin/javac', '-source', '8', '-target', '8',
    '-cp', framework, '-d', WORK/'classes', WORK/'KeyboardPresenceProbe.java'], check=True)
subprocess.run([ROM/'prebuilts/jdk/jdk21/linux-x86/bin/jar', 'cf', WORK/'probe.jar',
    '-C', WORK/'classes', '.'], check=True)
subprocess.run([ROM/'out/host/linux-x86/bin/d8', '--min-api', '35', '--output', WORK/'dex',
    WORK/'probe.jar'], check=True)
print(WORK/'dex/classes.dex')
