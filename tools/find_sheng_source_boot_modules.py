#!/usr/bin/env python3
"""Find the same-build first-stage and recovery module dependency closure."""
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
plan=json.loads((root/'sheng-module-plan.json').read_text())
print(' '.join(Path(p).name for p in plan['install']['vendor_boot']))
