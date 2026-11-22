#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compile the current app without touching a running Soong graph or API snapshot."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

DEVICE = Path(__file__).resolve().parents[1]
SOURCE = DEVICE/'interfaces/input/stylus'
CHARGE_SOURCE = DEVICE/'interfaces/input/pen/common'
ROM = Path('/root/sheng-lineage/lineage-24.0')
ROOT = DEVICE.parents[2]/'reports/device/20261114-stylus-service'
ROOT.mkdir(parents=True, exist_ok=True)
WORK = Path(tempfile.mkdtemp(prefix='java-compilation-', dir=ROOT))
environment = os.environ.copy()
environment.update(LANG='C.UTF-8', LC_ALL='C.UTF-8', LD_LIBRARY_PATH=str(ROM/'out/host/linux-x86/lib64'))
interface = SOURCE/'aidl/vendor/lineage/sheng/stylus/IPenController.aidl'
sources = (sorted((SOURCE/'src').rglob('*.java')) + sorted((SOURCE/'app').rglob('*.java'))
           + sorted(CHARGE_SOURCE.rglob('*.java')))
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(),
               kind='isolated-stylus-java-compilation',
               aidl_source_sha256=sha(interface), source_sha256={str(p):sha(p) for p in sources},
               normal_soong_module_build=False, installed=False, runtime_tested=False,
               compiler_wrapper_changed=False, public_source_changed=False, commands=[])
def run(command):
    result = subprocess.run(list(map(str, command)), env=environment, text=True, capture_output=True)
    receipt['commands'].append(dict(command=list(map(str, command)), exit_code=result.returncode,
                                     stdout=result.stdout, stderr=result.stderr))
    if result.returncode: raise RuntimeError(result.stderr)
try:
    run([ROM/'out/host/linux-x86/bin/aidl', '--structured', '--stability=vintf', '--version=1',
         '--min_sdk_version=35', '-I'+str(SOURCE/'aidl'), '--lang=java', '--out='+str(WORK/'generated'), interface])
    jars = [ROM/'out/soong/.intermediates/frameworks/base/framework-minus-apex/android_common/combined/framework.jar',
            ROM/'out/soong/.intermediates/packages/modules/Bluetooth/framework/framework-bluetooth.impl/android_common/combined/framework-bluetooth.jar',
            ROM/'out/soong/.intermediates/libcore/core-libart/android_common_apex31/javac/core-libart.jar']
    receipt['classpath_sha256'] = {str(path):sha(path) for path in jars}
    generated = list((WORK/'generated').rglob('*.java'))
    run([ROM/'prebuilts/jdk/jdk21/linux-x86/bin/javac', '-J-Xmx256m', '-source', '8', '-target', '8',
         '-Xlint:-options', '-encoding', 'UTF-8', '-cp', os.pathsep.join(map(str, jars)),
         '-d', WORK/'classes', *sources, *generated])
    receipt.update(passed=True, classes_sha256={str(p.relative_to(WORK)):sha(p) for p in sorted((WORK/'classes').rglob('*.class'))})
except Exception as error:
    receipt.update(passed=False, error=str(error))
(WORK/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
print(WORK)
print(json.dumps(dict(passed=receipt['passed'], kind=receipt['kind'],
                     source_count=len(sources), normal_soong_module_build=False, installed=False)))
if not receipt['passed']: print(receipt['error'])
raise SystemExit(0 if receipt['passed'] else 1)
