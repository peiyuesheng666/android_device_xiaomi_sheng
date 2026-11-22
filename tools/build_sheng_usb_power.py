#!/usr/bin/env python3
"""Build the independent USB power tile using the synchronized ROM toolchain."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import zipfile

w = Path(__file__).resolve().parents[4]
r = Path('/root/sheng-pixelos/android')
o = r / 'out-clean-ota-20261116'
source = w / 'device/xiaomi/sheng/interfaces/usb/power'
d = r.parent / 'diagnostics/usb-power-20261118'
a = w / 'artifacts/usb-power-20261118'
report = w / 'reports/usb-power-20261118'
java = r / 'prebuilts/jdk/jdk21/linux-x86/bin'
host = o / 'host/linux-x86/bin'
sdk = r / 'prebuilts/sdk/37.0/public/android.jar'
framework = o / 'soong/.intermediates/frameworks/base/framework-minus-apex/android_common/combined/framework.jar'
env = dict(os.environ, LANG='C.UTF-8', LC_ALL='C.UTF-8',
           JAVA_HOME=str(java.parent), PATH=str(java) + ':' + os.environ['PATH'])
for p in [d, a, report, d / 'compiled', d / 'generated', d / 'classes', d / 'dex']:
    p.mkdir(parents=True, exist_ok=True)

def run(name, args):
    p = subprocess.run(list(map(str, args)), env=env, cwd=r,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (report / (name + '.log')).write_text(p.stdout)
    if p.returncode:
        raise RuntimeError(name + ': ' + p.stdout[-6000:])
    return p.stdout

run('resources', [host / 'aapt2', 'compile', '--dir', source / 'res',
                  '-o', d / 'resources.zip'])
run('link', [host / 'aapt2', 'link', '-I', sdk, '--manifest', source / 'AndroidManifest.xml',
             '--java', d / 'generated', '-o', d / 'resources.apk', d / 'resources.zip'])
run('javac', [java / 'javac', '-encoding', 'UTF-8', '-source', '17', '-target', '17',
              '-classpath', str(framework) + ':' + str(sdk), '-d', d / 'classes',
              *sorted((source / 'src').rglob('*.java')), *sorted((d / 'generated').rglob('*.java'))])
run('jar', [java / 'jar', 'cf', d / 'classes.jar', '-C', d / 'classes', '.'])
run('dex', [host / 'd8', '--min-api', '33', '--lib', sdk,
            '--output', d / 'dex', d / 'classes.jar'])
with zipfile.ZipFile(d / 'resources.apk') as src, zipfile.ZipFile(d / 'unsigned.apk', 'w') as dst:
    for item in src.infolist():
        dst.writestr(item, src.read(item.filename))
    for p in (d / 'dex').glob('*.dex'):
        dst.write(p, p.name, compress_type=zipfile.ZIP_STORED)
run('align', [host / 'zipalign', '-P', '16', '-f', '4', d / 'unsigned.apk', d / 'aligned.apk'])
signer = r / 'prebuilts/sdk/tools/linux/lib/apksigner.jar'
security = r / 'build/target/product/security'
apk = a / 'ShengUsbPower.apk'
run('sign', [java / 'java', '-jar', signer, 'sign', '--key', security / 'platform.pk8',
             '--cert', security / 'platform.x509.pem', '--out', apk, d / 'aligned.apk'])
verify = run('verify', [java / 'java', '-jar', signer, 'verify', '--verbose', '--print-certs', apk])
baseline = run('baseline-cert', [java / 'java', '-jar', signer, 'verify', '--print-certs',
                w / 'artifacts/desktop-home-transition-20261118/SystemUI.apk'])
pattern = r'certificate SHA-256 digest: ([0-9a-f]+)'
assert re.search(pattern, verify).group(1) == re.search(pattern, baseline).group(1)
record = dict(built=True, installed=False, platform_certificate_matches=True,
              apk_sha256=hashlib.sha256(apk.read_bytes()).hexdigest(), bytes=apk.stat().st_size,
              sources={str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in source.rglob('*') if p.is_file()})
(report / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2))
