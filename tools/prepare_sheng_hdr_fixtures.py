#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate Main10 PQ/HLG clips and independent per-frame references."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import subprocess


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--width', type=int, default=320)
    parser.add_argument('--height', type=int, default=192)
    parser.add_argument('--frames', type=int, default=12)
    parser.add_argument('--fps', type=int, default=24)
    args = parser.parse_args()
    width, height, count, fps = args.width, args.height, args.frames, args.fps
    if not (64 <= width <= 3840 and 64 <= height <= 2160 and width % 2 == 0
            and height % 2 == 0 and 8 <= count <= 120 and 1 <= fps <= 60):
        parser.error('Use even dimensions up to 3840x2160, 8-120 frames and 1-60 fps')
    if width * height * 3 * count > 1024 ** 3:
        parser.error('Each uncompressed fixture must stay within 1 GiB')
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    assert work.stat().st_dev == Path('/').stat().st_dev, 'Use native C-backed WSL storage'
    frame_bytes = width * height * 3
    raw = work / 'generated.yuv'
    with raw.open('wb') as stream:
        for frame in range(count):
            for plane in range(3):
                divisor = 1 if plane == 0 else 2
                for y in range(height // divisor):
                    row = [64 + (x * 13 + y * 7 + frame * 37 + plane * 149) % 877
                           for x in range(width // divisor)]
                    stream.write(struct.pack('<' + 'H' * len(row), *row))
    assert raw.stat().st_size == frame_bytes * count
    print(f'Generated {count} Main10 frames at {width}x{height}', flush=True)
    commands = []

    def run(label, command):
        print(label, flush=True)
        result = subprocess.run(list(map(str, command)), capture_output=True, timeout=180)
        (work / (label + '.stdout')).write_bytes(result.stdout)
        (work / (label + '.stderr')).write_bytes(result.stderr)
        commands.append(dict(label=label, command=list(map(str, command)), returncode=result.returncode))
        result.check_returncode()
        return result.stdout

    refs = {}
    for name, transfer, android_transfer in [('pq', 'smpte2084', 6), ('hlg', 'arib-std-b67', 7)]:
        clip = work / (name + '.mp4')
        params = 'pools=2:frame-threads=1:bframes=0:keyint=12:repeat-headers=1'
        static = ''
        if name == 'pq':
            params += ':hdr10=1:master-display=G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,50):max-cll=1000,400'
            static = struct.pack('<B12H', 0, 34000, 16000, 13250, 34500, 7500, 3000,
                                 15635, 16450, 1000, 50, 1000, 400).hex()
        run(name + '-encode', ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin',
            '-f', 'rawvideo', '-pixel_format', 'yuv420p10le', '-video_size', f'{width}x{height}',
            '-framerate', str(fps), '-i', raw, '-frames:v', str(count), '-an', '-c:v', 'libx265',
            '-preset', 'fast', '-crf', '18', '-profile:v', 'main10', '-x265-params', params,
            '-color_range', 'tv', '-color_primaries', 'bt2020', '-colorspace', 'bt2020nc',
            '-color_trc', transfer, '-tag:v', 'hvc1', clip])
        probe = json.loads(run(name + '-ffprobe', ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_streams', '-show_frames', '-of', 'json', clip]))
        stream = probe['streams'][0]
        assert stream['codec_name'] == 'hevc' and stream['profile'] == 'Main 10'
        assert stream['pix_fmt'] == 'yuv420p10le' and stream['color_transfer'] == transfer
        assert stream['color_range'] == 'tv' and stream['color_primaries'] == 'bt2020'
        assert len(probe['frames']) == count
        decoded = work / (name + '-reference.yuv')
        run(name + '-decode', ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin',
            '-threads', '2', '-i', clip, '-map', '0:v:0', '-an', '-pix_fmt', 'yuv420p10le',
            '-f', 'rawvideo', decoded])
        assert decoded.stat().st_size == frame_bytes * count
        frames = []
        with decoded.open('rb') as decoded_stream:
            for frame in probe['frames']:
                data = decoded_stream.read(frame_bytes)
                assert len(data) == frame_bytes
                frames.append(dict(pts_us=round(float(frame['best_effort_timestamp_time']) * 1_000_000),
                                   sha256=hashlib.sha256(data).hexdigest()))
            assert decoded_stream.read(1) == b''
        reference = dict(width=width, height=height, bit_depth=10, frames=frames,
                         fixture_sha256=sha(clip), reference_yuv_sha256=sha(decoded),
                         source_yuv_sha256=sha(raw), generated_locally=True,
                         **{'color-standard': 6, 'color-transfer': android_transfer, 'color-range': 2,
                            'hdr_static_info': static})
        path = work / (name + '-reference.json')
        path.write_text(json.dumps(reference, indent=2) + '\n')
        refs[name] = dict(clip_sha256=sha(clip), reference_sha256=sha(path), frames=count)
    receipt = dict(passed=True, date_utc=datetime.now(timezone.utc).isoformat(),
                   width=width, height=height, frame_count=count, frame_rate=fps,
                   source_sha256=sha(Path(__file__)), fixtures=refs, commands=commands,
                   network_used=False, camera_used=False, screenshot_taken=False)
    (work / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(dict(passed=True, work=str(work), fixtures=refs)))


if __name__ == '__main__':
    main()
