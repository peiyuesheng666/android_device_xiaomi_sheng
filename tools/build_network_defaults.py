"""Build sheng's network resource overlays with retained Android build tools (WSL)."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess

DEVICE = Path(__file__).resolve().parents[1]
WORKSPACE = DEVICE.parents[2]
ANDROID = Path('/root/sheng-pixelos/android')
OUT = ANDROID / 'out-clean-ota-20261116'
HOST = OUT / 'host/linux-x86'
BUILD = ANDROID.parent / 'diagnostics/network-defaults-20261118'
ARTIFACT = WORKSPACE / 'artifacts/network-defaults-20261118'
os.environ.update(LANG='C.UTF-8', LC_ALL='C.UTF-8')
BUILD.mkdir(parents=True, exist_ok=True)
ARTIFACT.mkdir(parents=True, exist_ok=True)
framework = OUT / 'soong/.intermediates/frameworks/base/core/res/framework-res/android_common/package-res.apk'
receipt = {'compiled': True, 'installed': False, 'overlays': []}
for name in ('FrameworkResOverlaySheng', 'NetworkStackResOverlaySheng'):
    source = DEVICE / 'overlay' / name
    shutil.copytree(source, ANDROID / 'device/xiaomi/sheng/overlay' / name, dirs_exist_ok=True)
    build = BUILD / name
    build.mkdir(exist_ok=True)
    commands = [
        [HOST / 'bin/aapt2', 'compile', '--dir', source / 'res', '-o', build / 'resources.zip'],
        [HOST / 'bin/aapt2', 'link', '-I', framework, '--manifest', source / 'AndroidManifest.xml',
         '--auto-add-overlay', '--min-sdk-version', '29', '--target-sdk-version', '36',
         '-o', build / 'unsigned.apk', build / 'resources.zip'],
        [ANDROID / 'prebuilts/jdk/jdk21/linux-x86/bin/java',
         '-Djava.library.path=' + str(HOST / 'lib64'), '-jar', HOST / 'framework/signapk.jar',
         ANDROID / 'build/target/product/security/testkey.x509.pem',
         ANDROID / 'build/target/product/security/testkey.pk8', build / 'unsigned.apk',
         build / (name + '.apk')],
        [HOST / 'bin/apksigner', 'verify', '--verbose', build / (name + '.apk')],
    ]
    for index, command in enumerate(commands):
        with (build / (str(index) + '.log')).open('w') as log:
            subprocess.run(list(map(str, command)), check=True, stdout=log, stderr=subprocess.STDOUT)
    apk = build / (name + '.apk')
    shutil.copyfile(apk, ARTIFACT / apk.name)
    receipt['overlays'].append({'name': name, 'sha256': hashlib.sha256(apk.read_bytes()).hexdigest()})
shutil.copyfile(DEVICE / 'device.mk', ANDROID / 'device/xiaomi/sheng/device.mk')
(WORKSPACE / 'reports/network-defaults-build-20261118.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2))
