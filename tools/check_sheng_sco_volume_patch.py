#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check the sheng SCO fix against real PixelOS input without editing it."""
import argparse
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('rom', type=Path)
args = parser.parse_args()
relative = Path('frameworks/base/services/core/java/com/android/server/audio/AudioService.java')
original = (args.rom / relative).read_bytes()
patch = Path(__file__).resolve().parents[1] / 'interfaces/audio/sheng-sco-volume-driver.patch'
with tempfile.TemporaryDirectory(prefix='sheng-sco-check-') as tmp:
    staged = Path(tmp) / relative
    staged.parent.mkdir(parents=True)
    staged.write_bytes(original)
    subprocess.run(['patch', '--batch', '--forward', '--fuzz=0', '-p1'], cwd=tmp,
                   input=patch.read_bytes().replace(b'\r\n', b'\n'), check=True)
    updated = staged.read_bytes()
    marker = b'// The sheng policy routes HFP playback to the headset variant.'
    assert updated.count(marker) == 1 and updated != original
    subprocess.run(['patch', '--batch', '--reverse', '--fuzz=0', '-p1'], cwd=tmp,
                   input=patch.read_bytes().replace(b'\r\n', b'\n'), check=True)
    assert staged.read_bytes() == original
assert (args.rom / relative).read_bytes() == original
print('PASS: SCO patch applies and reverses byte-for-byte in a temporary copy')
