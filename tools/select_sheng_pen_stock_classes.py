#!/usr/bin/env python3
from pathlib import Path
import re

WORK = Path('/root/sheng-lineage/hardware-diagnostics/sheng-accessories-r53-20261111/pen-stock-review')
source = WORK/'classes.dex.disassembly.txt'
selected = []
block = []
def retain(lines):
    text = ''.join(lines)
    if any(key in text for key in ['MIPP_PEN_STATE', 'mMippDescriptor', 'Pen BLE param',
            'const-string v0, "sheng"', 'const-string v1, "sheng"']):
        descriptor = re.search(r"Class descriptor\s*: '([^']+)'", text)
        if descriptor:
            name = descriptor[1].strip('L;').replace('/', '_')
            (WORK/(name+'.txt')).write_text(text)
            selected.append((name, len(lines)))
with source.open(errors='replace') as stream:
    for line in stream:
        if line.startswith('Class #') and block:
            retain(block)
            block = []
        block.append(line)
    retain(block)
print(selected)
