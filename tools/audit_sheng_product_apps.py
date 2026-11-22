#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check the product placement of device applications and their permission files."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


def modules(text):
    # Braces inside quoted strings and comments are not Blueprint structure.
    text = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/',
                  lambda m: m[0] if m[0].startswith('"') else ' '*len(m[0]), text)
    for match in re.finditer(r'(?m)^(\w+)\s*\{', text):
        start = match.end()
        depth = 1
        for token in re.finditer(r'"(?:\\.|[^"\\])*"|[{}]', text[start:]):
            if token[0] == '{': depth += 1
            elif token[0] == '}': depth -= 1
            if depth == 0:
                body = text[start:start+token.start()]
                name = re.search(r'\bname:\s*"([^"\n]+)"', body)
                if name: yield name[1], (match[1], body)
                break
        else: raise ValueError('Unbalanced Blueprint module')


def audit(device):
    catalog_path = device/'configs/product-apps.json'
    catalog = json.loads(catalog_path.read_text())
    assert catalog['partition'] == 'product'
    rows = catalog['applications'] + catalog['uninstalled_applications'] + catalog['companions']
    known = {r['module'] for r in catalog['applications']+catalog['uninstalled_applications']}
    products = ('lineage_sheng', 'custom_sheng')
    input_paths = {'configs/product-apps.json', 'device.mk', 'AndroidProducts.mk',
                   'product-common.mk', 'proprietary-files.txt'}
    input_paths.update(product+'.mk' for product in products)
    checked = []
    for row in rows:
        if row.get('new_source'):
            input_paths.update((row['new_source'], 'interfaces/input/ime/source.json', 'interfaces/input/ime/NOTICE'))
        if 'blueprint' in row:
            input_paths.add(row['blueprint'])
            kind, body = dict(modules((device/row['blueprint']).read_text()))[row['module']]
            assert re.search(r'\bproduct_specific:\s*true\b', body), row['module']
            assert not re.search(r'\b(system_ext_specific|soc_specific|device_specific):\s*true\b', body), row['module']
            checked.append(row['module'])
        elif 'proprietary_source' in row:
            lines = (device/'proprietary-files.txt').read_text().splitlines()
            assert lines.count(row['proprietary_source']) == 1
            assert not any('MiAONService.apk:' in line for line in lines)
            checked.append(row['module'])
        elif 'copy_file_source' in row:
            input_paths.add(row['copy_file_source'])
            wanted = '$(LOCAL_PATH)/'+row['copy_file_source']+':$(TARGET_COPY_OUT_PRODUCT)/'+row['path']
            assert wanted in (device/'device.mk').read_text()
    for directory in ('interfaces', 'dolby'):
        for path in (device/directory).rglob('Android.bp'):
            if 'cache' in path.relative_to(device).parts: continue
            for name, (kind, body) in modules(path.read_text()):
                if kind not in ('android_app', 'android_app_import'): continue
                assert name in known, 'Register the added application in configs/product-apps.json: '+name
                assert re.search(r'\bproduct_specific:\s*true\b', body), name
    for product in products:
        entry = (device/(product+'.mk')).read_text()
        assert entry.count('$(call inherit-product, device/xiaomi/sheng/device.mk)') == 1, product
        assert len(re.findall(r'^include\s+device/xiaomi/sheng/product-common\.mk\s*$', entry, re.M)) == 1, product
        assert re.search(r'^PRODUCT_NAME\s*:=\s*'+product+r'\s*$', entry, re.M), product
        assert not re.search(r'^\s*(?:override\s+)?(?:OVERRIDE_)?PRODUCT_ENFORCE_PRODUCT_PARTITION_INTERFACE\b',
                             entry, re.M), 'Keep the product API policy in product-common.mk'
    configuration = (device/'product-common.mk').read_text()
    assignments = re.findall(
        r'^(?:override\s+)?PRODUCT_ENFORCE_PRODUCT_PARTITION_INTERFACE\s*[:?+]?=.*$',
        configuration, re.M)
    assert len(assignments) == 1 and re.fullmatch(
        r'override PRODUCT_ENFORCE_PRODUCT_PARTITION_INTERFACE\s*:=\s*false\s*',
        assignments[0]), 'The product interface choice must survive the shipping-API default'
    assert not re.search(r'^\s*(?:override\s+)?OVERRIDE_PRODUCT_ENFORCE_PRODUCT_PARTITION_INTERFACE\b',
                         configuration, re.M), 'Do not use the obsolete testing-only override'
    paths = [r['path'] for r in catalog['applications']+catalog['companions']]
    ime_body = dict(modules((device/'interfaces/input/ime/Android.bp').read_text()))['ShengSogouIme'][1]
    override_list = re.search(r'\boverrides:\s*\[([^]]*)\]', ime_body)
    overrides = set(re.findall(r'"([^"]+)"', override_list[1])) if override_list else set()
    assert not overrides, 'Keep each ROM input method available'
    assert 'ShengSogouIme' in {row['module'] for row in catalog['uninstalled_applications']}
    for relative in ('device.mk', 'product-common.mk', *(name+'.mk' for name in products)):
        text = (device/relative).read_text()
        assert not re.search(r'^\s*PRODUCT_PACKAGES\s*\+?=.*\bShengSogouIme\b', text, re.M), relative
    assert len(set(paths)) == len(paths)
    assert len(set(r['package'] for r in catalog['applications'])) == len(catalog['applications'])
    return dict(passed=True, application_count=len(catalog['applications']), checked_modules=checked,
                source_sha256={p: hashlib.sha256((device/p).read_bytes()).hexdigest() for p in sorted(input_paths)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--reference-device', type=Path,
                        help='Require identical layout inputs in this source device tree')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.device.resolve())
    if args.reference_device:
        assert result == audit(args.reference_device.resolve()), 'Product layout source mirror differs'
    result['date_utc'] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream: json.dump(result, stream, indent=2); stream.write('\n')
    print(json.dumps(dict(passed=True, application_count=result['application_count'], output=str(args.output))))


if __name__ == '__main__':
    main()
