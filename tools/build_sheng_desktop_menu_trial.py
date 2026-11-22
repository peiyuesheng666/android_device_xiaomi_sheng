#!/usr/bin/env python3
"""Build an uninstallable menu-only trial RRO; never install or edit ROM sources."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--root', type=Path, required=True)
p.add_argument('--apksigner', type=Path, required=True)
a = p.parse_args()
r = a.root.resolve()
out = r / 'out-sheng-full-clean-20261122'
settings = out / 'target/product/sheng/system_ext/priv-app/Settings/Settings.apk'
source = r / 'device/xiaomi/sheng/overlay/SettingsResOverlaySheng/res-pixelos'
d = Path(tempfile.mkdtemp(prefix='desktop-menu-trial-', dir=r.parent / 'diagnostics'))
res = d / 'res'
files = []
for directory in ('xml', 'xml-zh'):
    for name in ('system_dashboard_fragment.xml', 'system_dashboard_fragment_desktop.xml'):
        src = source / directory / name
        dest = res / directory / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        files.append(str(src))
manifest = d / 'AndroidManifest.xml'
manifest.write_text('''<manifest xmlns:android="http://schemas.android.com/apk/res/android"
 package="org.lineageos.settingsoverlay.xiaomi.sheng.menutrial" android:versionCode="1">
 <uses-sdk android:minSdkVersion="35" android:targetSdkVersion="36"/>
 <application android:hasCode="false"/>
 <overlay android:targetPackage="com.android.settings" android:isStatic="false" android:priority="999"/>
</manifest>''')
env = dict(os.environ)
env['JAVA_HOME'] = str(r / 'prebuilts/jdk/jdk21/linux-x86')
def run(*args):
    subprocess.run(list(map(str, args)), cwd=d, env=env, check=True)
tool = out / 'host/linux-x86/bin/aapt2'
run(tool, 'compile', '--dir', res, '-o', d / 'res.zip')
run(tool, 'link', '--manifest', manifest, '-I', r / 'prebuilts/sdk/current/public/android.jar',
    '-I', settings, '-R', d / 'res.zip', '--auto-add-overlay', '--package-id', '0x80',
    '--allow-reserved-package-id', '-o', d / 'unsigned.apk')
apk = d / 'ShengDesktopMenuTrial.apk'
run(Path(env['JAVA_HOME']) / 'bin/java', '-jar', a.apksigner, 'sign',
    '--key', r / 'build/target/product/security/platform.pk8',
    '--cert', r / 'build/target/product/security/platform.x509.pem',
    '--out', apk, d / 'unsigned.apk')
receipt = dict(apk=str(apk), sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),
               source_xml=files, installed=False, flashed=False,
               scope='temporary menu overlay only; production static RRO unchanged')
(d / 'result.json').write_text(json.dumps(receipt, indent=2))
print(json.dumps(receipt))
