#!/usr/bin/env python3
"""Build a scoped SystemUI candidate using retained ROM classes and installed APK resources."""
from pathlib import Path
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import zipfile

W = Path(__file__).resolve().parents[4]
R = Path('/root/sheng-pixelos/android')
O = R / 'out-clean-ota-20261116'
D = R.parent / 'diagnostics/desktop-home-transition-20261118'
A = W / 'artifacts/desktop-home-transition-20261118'
REPORT = W / 'reports/desktop-home-transition-20261118'
BASE_APK = W / 'artifacts/desktop-qs-20261118/SystemUI.apk'
BASE_SHA = '3c95f6a996f523a43b384571f56b0e67cc5f43d0a001e85e14ca73c1a7e053fd'
BASE_CLASSES = O / 'soong/.intermediates/frameworks/base/packages/SystemUI/SystemUI/android_common/withres/SystemUI.jar'
FRAMEWORK = O / 'soong/.intermediates/frameworks/base/framework-minus-apex/android_common/combined/framework.jar'
SDK = R / 'prebuilts/sdk/37.0/public/android.jar'
JAVA = R / 'prebuilts/jdk/jdk21/linux-x86/bin'
HOST = O / 'host/linux-x86'

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def run(name, argv):
    with (REPORT / (name + '.log')).open('w') as log:
        p = subprocess.run(list(map(str, argv)), cwd=R, env=ENV,
                           stdout=log, stderr=subprocess.STDOUT)
    assert p.returncode == 0, (name, (REPORT / (name + '.log')).read_text()[-7000:])

assert sha(BASE_APK) == BASE_SHA, 'Installed SystemUI baseline changed'
assert not (A / 'SystemUI.apk').exists(), 'Preserve previous candidate and receipts'
for directory in [D, A, REPORT, D / 'classes', D / 'dex', D / 'probe-dex']:
    directory.mkdir(parents=True, exist_ok=True)
ENV = dict(os.environ, LANG='C.UTF-8', LC_ALL='C.UTF-8',
           JAVA_HOME=str(JAVA.parent), PATH=str(JAVA) + ':' + os.environ['PATH'])
source = W / 'device/xiaomi/sheng'
run('prepare', ['python3', source / 'tools/prepare_sheng_desktop_shell.py', '--rom', R])
shell = R / 'frameworks/base/libs/WindowManager/Shell/src/com/android/wm/shell/transition'
sources = [shell / 'RemoteTransitionHandler.java', shell / 'ShengDesktopHomeTransition.java']
run('javac', [JAVA / 'javac', '-source', '17', '-target', '17', '-Xlint:-options',
    '-cp', ':'.join(map(str, [FRAMEWORK, BASE_CLASSES, SDK])), '-d', D / 'classes', *sources,
    source / 'tools/ShengDesktopHomeTransitionProbe.java'])
replacements = {p.relative_to(D / 'classes').as_posix(): p
                for p in (D / 'classes').rglob('*.class')
                if p.name != 'ShengDesktopHomeTransitionProbe.class'}
assert replacements and all(p.startswith(('com/android/wm/shell/transition/RemoteTransitionHandler',
    'com/android/wm/shell/transition/ShengDesktopHomeTransition')) for p in replacements)
with zipfile.ZipFile(BASE_CLASSES) as original, zipfile.ZipFile(D / 'combined.jar', 'w') as target:
    for item in original.infolist():
        if item.filename.endswith('.class') and not item.filename.startswith(
                'com/android/wm/shell/transition/RemoteTransitionHandler'):
            target.writestr(item, original.read(item.filename))
    for name, path in replacements.items():
        target.write(path, name)
with zipfile.ZipFile(D / 'probe-classes.jar', 'w') as target:
    for path in (D / 'classes').rglob('ShengDesktopHomeTransition*.class'):
        target.write(path, path.relative_to(D / 'classes').as_posix())
run('probe-dex', [JAVA / 'java', '-Xmx512m', '-cp', R / 'prebuilts/r8/r8.jar',
    'com.android.tools.r8.D8', '--lib', SDK, '--classpath', BASE_CLASSES, '--classpath', FRAMEWORK,
    '--min-api', '37', '--output', D / 'probe-dex', D / 'probe-classes.jar'])
with zipfile.ZipFile(A / 'transition-probe.jar', 'w') as target:
    target.write(D / 'probe-dex/classes.dex', 'classes.dex')
print('Java compilation and diagnostic dex passed; optimizing with the ROM build rules.', flush=True)
# Reuse the actual generated R8 flags, including platform libraries and keep rules.
# Parse the command as arguments and redirect every output into this candidate directory.
# Never execute Ninja's surrounding cleanup commands or overwrite its retained build inputs.
mini = R.parent / 'diagnostics/desktop-systemui-20261118/scoped-settings.ninja'
target = str((O / 'soong/.intermediates/frameworks/base/packages/SystemUI/SystemUI/android_common/dex/SystemUI.jar').relative_to(R))
commands = subprocess.check_output([R / 'prebuilts/build-tools/linux-x86/bin/ninja',
    '-f', mini, '-t', 'commands', target], cwd=R, text=True)
parts = [part for line in commands.splitlines() for part in line.split(' && ')
         if '/bin/r8 ' in part]
assert len(parts) == 1, 'Generated R8 command changed'
argv = shlex.split(parts[0])
assert argv.pop(0).startswith('PATH=')
outputs = {'-injars': D / 'combined.jar', '--output': D / 'dex',
    '--resource-output': D / 'resources-shrunken.apk', '-printmapping': D / 'mapping.txt',
    '-printconfiguration': D / 'configuration.txt', '-printusage': D / 'unused.txt',
    '--deps-file': D / 'dex-dependencies.txt'}
for option, path in outputs.items():
    assert argv.count(option) == 1, option
    argv[argv.index(option) + 1] = str(path)
for i, arg in enumerate(argv[:-1]):
    if arg in ('--lib', '-include', '--resource-input', '-injars'):
        assert (R / argv[i + 1]).is_file(), 'Missing R8 input: ' + argv[i + 1]
(REPORT / 'r8-argv.json').write_text(json.dumps(argv, indent=2))
run('r8', argv)
with zipfile.ZipFile(BASE_APK) as original, zipfile.ZipFile(D / 'unsigned.apk', 'w') as target:
    for item in original.infolist():
        if not re.fullmatch(r'classes\d*\.dex', item.filename) and not item.filename.startswith('META-INF/'):
            target.writestr(item, original.read(item.filename))
    for path in sorted((D / 'dex').glob('*.dex')):
        target.write(path, path.name, compress_type=zipfile.ZIP_STORED)
run('align', [HOST / 'bin/zipalign', '-P', '16', '-f', '4', D / 'unsigned.apk', D / 'aligned.apk'])
signer = R / 'prebuilts/sdk/tools/linux/lib/apksigner.jar'
security = R / 'build/target/product/security'
run('sign', [JAVA / 'java', '-jar', signer, 'sign', '--key', security / 'platform.pk8',
    '--cert', security / 'platform.x509.pem', '--out', A / 'SystemUI.apk', D / 'aligned.apk'])
def cert(name, apk):
    run(name, [JAVA / 'java', '-jar', signer, 'verify', '--verbose', '--print-certs', apk])
    return re.search(r'certificate SHA-256 digest: ([0-9a-f]+)',
                     (REPORT / (name + '.log')).read_text()).group(1)
assert cert('candidate-signature', A / 'SystemUI.apk') == cert('baseline-signature', BASE_APK)
with zipfile.ZipFile(BASE_APK) as original, zipfile.ZipFile(A / 'SystemUI.apk') as candidate:
    resources = [n for n in original.namelist() if not re.fullmatch(r'classes\d*\.dex', n)
                 and not n.startswith('META-INF/')]
    assert all(original.read(n) == candidate.read(n) for n in resources), 'Resource regression'
record = dict(built=True, installed=False, baseline_sha256=BASE_SHA,
    candidate_sha256=sha(A / 'SystemUI.apk'), candidate_bytes=(A / 'SystemUI.apk').stat().st_size,
    resources_preserved=True, certificate_matches=True, rom_r8_rules_reused=True,
    changed_classes=sorted(replacements),
    source_sha256={str(p.relative_to(R)): sha(p) for p in sources})
(REPORT / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2), flush=True)
