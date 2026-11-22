#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read-only review of the retained live 5.15 module's pen count accessors."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

workspace = Path(__file__).resolve().parents[4]
work = workspace/'reports/device/20261114-stylus-service/live-driver-read-review'
module = work/'nt36532_touch.ko'
digest = hashlib.sha256(module.read_bytes()).hexdigest()
if digest != 'edf8001b0965f0e6d5005a7d8605a1b77d1d2949049c7ee5ef13a23a045db9e1':
    raise RuntimeError('Module differs from the physically accepted 5.15 baseline')
clang = Path('/root/sheng-lineage/lineage-24.0/prebuilts/clang/host/linux-x86/clang-r596125/bin')
symbols = subprocess.check_output([clang/'llvm-nm', module], text=True)
(work/'symbols.txt').write_text(symbols)
names = [line.split()[-1] for line in symbols.splitlines() if len(line.split()) >= 3]
selected = [name for name in names if name.startswith(('nvt_set_cur_value',
    'nvt_get_cur_value', 'nvt_get_mode_value', 'nvt_get_def_value', 'nvt_reset_mode'))]
if not any(name.startswith('nvt_set_cur_value') for name in selected):
    raise RuntimeError('Actual module setter symbol was not found')
outputs = {}
for index, name in enumerate(selected):
    result = subprocess.run([clang/'llvm-objdump', '--disassemble-symbols='+name,
        '--reloc', module], text=True, capture_output=True, check=True)
    if '<'+name+'>:' not in result.stdout:
        raise RuntimeError('Empty or mismatched disassembly for '+name)
    path = work/(str(index)+'-'+name.split('.')[0]+'.txt')
    path.write_text(result.stdout)
    outputs[name] = str(path.relative_to(workspace))
receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), module_sha256=digest,
    serial='ca10ede3', slot='_a', kernel='5.15.220-gf9ca2b71f672',
    symbol_list=str((work/'symbols.txt').relative_to(workspace)), functions=outputs,
    disassembly_nonempty=True, read_only=True, driver_commands_sent=False,
    connection_counter_readback_validated=False, native_crash_recovery_passed=False)
(work/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
print(json.dumps(receipt, indent=2))
