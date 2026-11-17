#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compile and exercise the pen's gesture state and accessory command boundaries."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    os.environ.update(LANG='C.UTF-8', LC_ALL='C.UTF-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    device = Path(__file__).resolve().parents[1]
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    work = Path(tempfile.mkdtemp(prefix='pen-button-tests-', dir=out))
    jdk = Path(os.environ.get('SHENG_ROM_ROOT', '/root/sheng-pixelos/android'))/'prebuilts/jdk/jdk21/linux-x86/bin'
    stylus = device/'interfaces/input/stylus'
    common = device/'interfaces/input/pen/common'
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    snapshot = lambda: {p.relative_to(device).as_posix(): digest(p)
        for root in (stylus, device/'interfaces/input/pen') for p in sorted(root.rglob('*')) if p.is_file()}
    before = snapshot()
    sources = [common/'org/lineageos/sheng/pen/controls/PenControls.java',
               common/'org/lineageos/sheng/pen/controls/PenMenuEntry.java',
               stylus/'src/org/lineageos/sheng/stylus/PenCardGesture.java',
               stylus/'src/org/lineageos/sheng/stylus/PenButtonState.java',
               stylus/'src/org/lineageos/sheng/stylus/PenFeatureCommands.java',
               stylus/'src/org/lineageos/sheng/stylus/PenWakeGate.java',
               stylus/'tests/PenButtonsTest.java']
    receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), passed=False,
                   source_sha256=before, hardware_gestures_verified=False,
                   normal_module_build_passed=False, full_product_build_passed=False)
    try:
        build = subprocess.run([str(jdk/'javac'), '-encoding', 'UTF-8', '-d', str(work/'classes'),
                                *map(str, sources)], capture_output=True, text=True, timeout=60)
        (out/'javac.log').write_text(build.stdout+build.stderr); build.check_returncode()
        result = subprocess.run([str(jdk/'java'), '-cp', str(work/'classes'),
                                 'org.lineageos.sheng.stylus.PenButtonsTest'], capture_output=True, text=True, timeout=30)
        (out/'tests.log').write_text(result.stdout+result.stderr); result.check_returncode()
        assert before == snapshot()
        receipt.update(passed=True, assertions=int(re.search(r'pen_button_checks=(\d+)', result.stdout)[1]),
                       work_dir=str(work))
    finally:
        (out/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(dict(passed=True, assertions=receipt['assertions'], output=str(out))))


if __name__ == '__main__':
    main()
