#!/usr/bin/env python3
"""Disassemble the original BLE extension for read-only protocol review."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import zipfile

ROOT = Path('/root/sheng-lineage')
WORK = ROOT/'hardware-diagnostics/sheng-accessories-r53-20261111/pen-stock-review'
WORK.mkdir(parents=True, exist_ok=True)
APK = ROOT/'firmware-dump/partitions/system_ext/app/BluetoothExtension/BluetoothExtension.apk'
HOST = ROOT/'lineage-24.0/out/host/linux-x86'
os.environ['LD_LIBRARY_PATH'] = str(HOST/'lib64')
with zipfile.ZipFile(APK) as archive:
    names = [name for name in archive.namelist() if name.endswith('.dex')]
    for name in names:
        dex = WORK/name
        dex.write_bytes(archive.read(name))
        with (WORK/(name+'.disassembly.txt')).open('w') as output:
            subprocess.run([HOST/'bin/dexdump', '-d', dex], stdout=output, check=True)
(WORK/'provenance.json').write_text(json.dumps({'source': str(APK),
    'sha256': hashlib.sha256(APK.read_bytes()).hexdigest(), 'dex': names,
    'read_only_original': True}, indent=2)+'\n')
print(WORK)
