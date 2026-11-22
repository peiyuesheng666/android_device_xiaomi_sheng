#!/usr/bin/env python3
"""Offline guard for extracted sheng vendor/odm before restoring persist."""
import argparse
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('product', type=Path, help='Directory containing extracted vendor and odm')
p.add_argument('stock_odm', type=Path, help='Unmodified sheng stock ODM directory')
p.add_argument('--stock-vendor', type=Path, help='Also verify sheng stock SSC service, init RC, and registry config')
a = p.parse_args()
v = a.product / 'vendor'
odm = a.product / 'odm'
service = 'android.hardware.sensors-service.sheng-multihal'
required = [v / 'bin/hw' / service, v / 'etc/init' / (service + '.rc'),
            v / 'etc/init/vendor.sensors.sscrpcd.rc']
files = set(required)
for part in (v, odm):
    files.update((part / 'etc/init').rglob('*.rc'))
markers = (b'sheng-landscape-frame-v1', b'sheng-landscape-v2',
           b'--migrate-landscape-frame', b'--prepare-isolated-frame',
           b'--verify-isolated-frame', b'vendor.sheng.sensor_frame',
           b'vendor.sheng-sensor-frame')
for f in sorted(files):
    if any(m in f.read_bytes() for m in markers):
        p.exit(1, f'Calibration migration still present: {f}\n')
for name in ('sm8550_icm4x6xx_0.json', 'sm8550_qmc6308_0.json'):
    rel = Path('etc/sensors/config') / name
    if (odm / rel).read_bytes() != (a.stock_odm / rel).read_bytes():
        p.exit(1, f'ODM sensor config differs from stock: {rel}\n')
if a.stock_vendor:
    for rel in ('bin/sscrpcd', 'etc/init/vendor.sensors.sscrpcd.rc',
                'etc/sensors/sns_reg_config'):
        if (v / rel).read_bytes() != (a.stock_vendor / rel).read_bytes():
            p.exit(1, f'SSC vendor file differs from stock: {rel}\n')
print('PASS: sensor migration markers absent; both ODM sensor configs match stock'
      + ('; SSC vendor files match stock' if a.stock_vendor else ''))
