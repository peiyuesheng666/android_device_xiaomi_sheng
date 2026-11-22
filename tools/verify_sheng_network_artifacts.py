#!/usr/bin/env python3
"""Check exact network RRO contents and idmap compatibility in sheng product output."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

MIUI = 'connect.rom.miui.com/generate_204'
HICLOUD = 'connectivitycheck.platform.hicloud.com/generate_204'
CHECKS = (
    ('system/framework/framework-res.apk', 'odm/overlay/FrameworkResOverlaySheng.apk',
     'odm', ('org.lineageos.overlay.sheng.framework', 'android', 'XiaomiFrameworkResOverlay'),
     {'array/config_ntpServers': ['ntp://time.apple.com']}),
    ('system/priv-app/NetworkStack/NetworkStack.apk',
     'product/overlay/NetworkStackResOverlaySheng.apk', 'product',
     ('org.lineageos.overlay.sheng.networkstack', 'com.android.networkstack', 'NetworkStackConfig'), {
         'string/config_captive_portal_http_url': ['http://' + MIUI],
         'string/config_captive_portal_https_url': ['https://' + MIUI],
         'array/config_captive_portal_http_urls': ['http://' + MIUI],
         'array/config_captive_portal_https_urls': ['https://' + MIUI],
         'array/config_captive_portal_fallback_urls': ['http://' + HICLOUD, 'https://' + HICLOUD],
     }),
)


def run(*args):
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode:
        raise ValueError(f'{Path(args[0]).name}: {proc.stderr.strip() or proc.stdout.strip()}')
    return proc.stdout


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_manifest(aapt, apk, identity):
    package, target, overlayable = identity
    xml = run(aapt, 'dump', 'xmltree', '--file', 'AndroidManifest.xml', apk)
    if len(re.findall(r'(?m)^\s*E: overlay(?:\s|$)', xml)) != 1:
        raise ValueError('Expected exactly one overlay declaration')
    expected = {'package': f'"{package}"', 'targetPackage': f'"{target}"',
                'targetName': f'"{overlayable}"', 'isStatic': 'true',
                'priority': '800', 'hasCode': 'false'}
    for name, value in expected.items():
        pattern = rf'(?m)^\s*A: (?:http://schemas.android.com/apk/res/android:)?{name}(?:\(0x[0-9a-f]+\))?=([^\n]+)'
        matches = [item.split(' (Raw: ', 1)[0].strip() for item in re.findall(pattern, xml)]
        if matches != [value]:
            raise ValueError(f'Overlay manifest {name}: expected {value}, found {matches!r}')
    return {'package': package, 'target': target, 'target_overlayable': overlayable,
            'static': True, 'priority': 800, 'has_code': False}


def verify(product, host, target_files=False):
    def artifact(relative):
        partition, filename = relative.split('/', 1)
        return product / (partition.upper() if target_files else partition) / filename
    results = []
    with tempfile.TemporaryDirectory(prefix='sheng-network-idmap-') as folder:
        for index, (target, overlay, policy, identity, expected) in enumerate(CHECKS):
            row = {'target': target, 'overlay': overlay}
            results.append(row)
            try:
                target_path, overlay_path = artifact(target), artifact(overlay)
                for path in (target_path, overlay_path):
                    if not path.is_file():
                        raise ValueError(f'Missing artifact: {path}')
                row.update(target_sha256=sha(target_path), overlay_sha256=sha(overlay_path))
                row['manifest'] = check_manifest(host / 'aapt2', overlay_path, identity)
                idmap = Path(folder) / str(index)
                tool = host / 'idmap2'
                run(tool, 'create', '--target-apk-path', target_path, '--overlay-apk-path',
                    overlay_path, '--idmap-path', idmap, '--policy', 'public', '--policy', policy)
                mapped = run(tool, 'dump', '--idmap-path', idmap)
                values = run(host / 'aapt2', 'dump', 'resources', overlay_path)
                blocks = re.split(r'(?m)^\s*resource 0x[0-9a-f]+ ', values)[1:]
                for key, wanted in expected.items():
                    if f'({key} -> {key})' not in mapped:
                        raise ValueError(f'No idmap entry for {key}')
                    matches = [b for b in blocks if b.splitlines()[0].strip() == key]
                    found = re.findall(r'"([^"\n]*)"', matches[0]) if len(matches) == 1 else []
                    if found != wanted:
                        raise ValueError(f'{key}: expected {wanted!r}, found {found!r}')
                row['resources'] = expected
            except (ValueError, OSError) as error:
                row['error'] = str(error)
    return {'scope': ('target-files APK tree' if target_files else 'product staging APKs')
                      + '; not runtime or final image proof',
            'passed': all('error' not in row for row in results), 'checks': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    layout = parser.add_mutually_exclusive_group(required=True)
    layout.add_argument('--product', type=Path, help='out/target/product/sheng')
    layout.add_argument('--target-files-dir', type=Path, help='unpacked target-files layout')
    parser.add_argument('--host-bin', type=Path, required=True, help='out/host/linux-x86/bin')
    args = parser.parse_args()
    root = args.target_files_dir or args.product
    result = verify(root.resolve(), args.host_bin.resolve(), args.target_files_dir is not None)
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
