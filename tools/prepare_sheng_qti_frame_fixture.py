#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate a small deterministic AVC stream and independently decoded reference."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    width = height = 128
    count = fps = 8
    pixels = width * height
    raw = bytearray()
    for frame in range(count):
        raw.extend(16 + ((x * 3 + y * 2 + frame * 23) % 220)
                   for y in range(height) for x in range(width))
        raw.extend(bytes([64 + frame * 12]) * (pixels // 4))
        raw.extend(bytes([192 - frame * 12]) * (pixels // 4))
    original = work / 'source.yuv'
    original.write_bytes(raw)
    encoded = work / 'fixture.avc'
    reference = work / 'reference.yuv'
    commands = [
        ['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1', '-f', 'rawvideo',
         '-pixel_format', 'yuv420p', '-video_size', '128x128', '-framerate', str(fps),
         '-i', str(original), '-frames:v', str(count), '-an', '-c:v', 'libx264',
         '-profile:v', 'baseline', '-level:v', '3.0', '-pix_fmt', 'yuv420p',
         '-threads', '1', '-x264-params',
         'keyint=1:min-keyint=1:scenecut=0:bframes=0:aud=1:repeat-headers=1',
         '-crf', '18', '-f', 'h264', str(encoded)],
        ['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1', '-i', str(encoded),
         '-frames:v', str(count), '-pix_fmt', 'yuv420p', '-f', 'rawvideo', str(reference)],
    ]
    for index, command in enumerate(commands):
        result = subprocess.run(command, capture_output=True, timeout=45)
        (work / ('ffmpeg-' + str(index) + '.txt')).write_bytes(result.stdout + result.stderr)
        result.check_returncode()
    stream = encoded.read_bytes()
    decoded = reference.read_bytes()
    assert len(decoded) == count * pixels * 3 // 2
    nals = list(re.finditer(b'\x00\x00(?:\x00)?\x01', stream))
    starts = [nal.start() for nal in nals if stream[nal.end()] & 31 == 9]
    assert len(starts) == count and starts[0] == 0, starts
    bounds = starts + [len(stream)]
    frames = []
    for index in range(count):
        chunk = stream[bounds[index]:bounds[index + 1]]
        types = [chunk[nal.end()] & 31 for nal in re.finditer(b'\x00\x00(?:\x00)?\x01', chunk)]
        assert {5, 7, 8, 9} <= set(types), types
        assert 1 not in types, types
        yuv = decoded[index * pixels * 3 // 2:(index + 1) * pixels * 3 // 2]
        frames.append(dict(index=index, timestamp_us=index * 1000000 // fps,
                           offset=bounds[index], size=len(chunk), nal_types=types,
                           luma_sha256=sha(yuv[:pixels]), yuv_sha256=sha(yuv)))
    assert len({frame['luma_sha256'] for frame in frames}) == count
    # A simple, checked text index avoids introducing a JSON parser in the vendor probe.
    (work / 'fixture.index').write_text(''.join(
        f"{f['index']} {f['offset']} {f['size']} {f['timestamp_us']}\n" for f in frames))
    receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), passed=True,
                   width=width, height=height, frame_count=count, fps=fps,
                   format='AVC Annex B baseline, all IDR, AUD and repeated SPS/PPS',
                   fixture_sha256=sha(stream), source_sha256=sha(raw),
                   reference_sha256=sha(decoded), index_sha256=sha((work / 'fixture.index').read_bytes()),
                   generator_sha256=sha(Path(__file__).read_bytes()), commands=commands,
                   ffmpeg_version=subprocess.check_output(['ffmpeg', '-version'], text=True).splitlines()[0],
                   frames=frames, device_tested=False, video_failure_fixed=False)
    (work / 'fixture.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(dict(work=str(work), frame_count=count, bytes=len(stream), passed=True)))


if __name__ == '__main__':
    main()
