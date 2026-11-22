#!/usr/bin/env python3
"""Record original keyboard inputs and bind the OEM APK signer to a scoped domain."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--stock', type=Path, required=True)
args = parser.parse_args()
device = Path(__file__).resolve().parents[1]
paths = [
    'product/app/MiDevAuthService/MiDevAuthService.apk',
    'odm/bin/hw/vendor.xiaomi.hardware.keyboardnanoapp@1.0-service',
    'vendor/lib64/vendor.xiaomi.hardware.keyboardnanoapp@1.0.so',
    'odm/etc/init/vendor.xiaomi.hardware.keyboardnanoapp@1.0-service.rc',
    'odm/etc/vintf/manifest/vendor.xiaomi.hardware.keyboardnanoapp@1.0_manifest.xml',
    'odm/bin/midevauthd',
    'odm/lib64/libmidevauth.so',
    'odm/lib64/vendor.xiaomi.hardware.midevauth@1.0.so',
    'odm/etc/init/vendor.xiaomi.hardware.midevauth@1.0-service.rc',
    'odm/etc/vintf/manifest/manifest_vendor.xiaomi.hardware.midevauth.xml',
    'odm/bin/mtd@1.3',
    'odm/lib64/libmt@1.3.so',
]
hashes = {name: hashlib.sha256((args.stock / name).read_bytes()).hexdigest() for name in paths}
with zipfile.ZipFile(args.stock / paths[0]) as apk:
    pkcs7 = apk.read('META-INF/CERT.RSA')
pem = subprocess.check_output(['openssl', 'pkcs7', '-inform', 'DER', '-print_certs'], input=pkcs7)
certificates = re.findall(b'-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----', pem)
assert len(certificates) == 1, 'Review the signing chain before changing the domain mapping'
certificate = subprocess.check_output(['openssl', 'x509', '-outform', 'DER'], input=certificates[0])
policy = device / 'interfaces/input/keyboard/sepolicy/system_ext/private'
policy.mkdir(parents=True, exist_ok=True)
xml = ('<?xml version="1.0" encoding="utf-8"?>\n<!-- SPDX-License-Identifier: Apache-2.0 -->\n'
       '<policy>\n  <signer signature="' + certificate.hex() + '">\n'
       '    <package name="com.xiaomi.devauth"><seinfo value="sheng_devauth" /></package>\n'
       '  </signer>\n</policy>\n')
(policy / 'mac_permissions.xml').write_text(xml)
for version in ('31.0', '32.0', '33.0', '34.0', '202404', '202504', '202604'):
    directory = policy / 'compat' / version
    directory.mkdir(parents=True, exist_ok=True)
    (directory / (version + '.ignore.cil')).write_text(
        ';; New device-owned app domains have no counterpart in older system_ext policy.\n'
        '(type new_objects)\n(typeattribute new_objects)\n'
        '(typeattributeset new_objects (new_objects sheng_keyboard_app sheng_devauth_app))\n')
receipt = {'source': 'Original sheng firmware partition dump', 'sha256': hashes,
           'signer_certificate_sha256': hashlib.sha256(certificate).hexdigest(),
           'apk_policy': 'PRESIGNED, preprocessed; original APK and authentication decisions unchanged',
           'scope': 'Signer plus exact package name; no global OEM signer privilege grant',
           'mtd_interfaces': 'Use existing hardware/xiaomi 1.0–1.3 HIDL libraries in vendor/lib64'}
destination = device / 'configs/keyboard-auth-inputs.json'
destination.write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({'inputs': len(hashes), 'receipt': str(destination)}))
