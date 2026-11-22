#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compile the generated-frame Codec2 diagnostic without loading Soong."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default_rom = Path(__file__).resolve().parents[4]
    if not (default_rom / 'build/envsetup.sh').is_file():
        default_rom = Path('/root/sheng-pixelos/android')
    parser.add_argument('--rom', type=Path, default=default_rom)
    parser.add_argument('--work', type=Path, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--audio', action='store_true', help='Build the generated-PCM audio probe')
    modes.add_argument('--lossless-file', action='store_true', help='Compare file decoding to independent PCM')
    modes.add_argument('--media-capabilities', action='store_true', help='Inspect codecs, HDR declarations and empty DRM sessions')
    modes.add_argument('--hdr-video', action='store_true', help='Compare Main10 video and HDR metadata with an independent decoder')
    args = parser.parse_args()
    rom = args.rom.resolve(strict=True)
    source = Path(__file__).resolve().with_name('ShengHdrVideoProbe.java' if args.hdr_video
        else 'ShengMediaCapabilitiesProbe.java' if args.media_capabilities
        else 'ShengLosslessAudioFileProbe.java' if args.lossless_file
        else 'ShengAudioCodec2RoundTrip.java' if args.audio else 'ShengCodec2RoundTrip.java')
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    classes = work / 'classes'
    classes.mkdir()
    sdk = rom / 'prebuilts/sdk/37.0/public/android.jar'
    r8 = rom / 'prebuilts/r8/r8.jar'
    java = rom / 'prebuilts/jdk/jdk21/linux-x86/bin'
    source_hash = sha(source)
    env = dict(os.environ, LANG='C.UTF-8', LC_ALL='C.UTF-8')
    env.pop('LD_LIBRARY_PATH', None)
    command = [java / 'javac', '-J-Xmx256m', '-source', '8', '-target', '8',
               '-Xlint:-options', '-encoding', 'UTF-8', '-cp', sdk, '-d', classes, source]
    compiled = subprocess.run(list(map(str, command)), env=env, capture_output=True, text=True, timeout=60)
    (work / 'javac.log').write_text(compiled.stdout + compiled.stderr)
    compiled.check_returncode()
    jar = work / ('sheng-hdr-video.jar' if args.hdr_video
                 else 'sheng-media-capabilities.jar' if args.media_capabilities
                 else 'sheng-lossless-audio-file.jar' if args.lossless_file
                 else 'sheng-audio-codec2-roundtrip.jar' if args.audio else 'sheng-codec2-roundtrip.jar')
    dex = [java / 'java', '-Xmx256m', '-cp', r8, 'com.android.tools.r8.D8',
           '--min-api', '34', '--lib', sdk, '--output', jar, *sorted(classes.glob('*.class'))]
    result = subprocess.run(list(map(str, dex)), env=env, capture_output=True, text=True, timeout=60)
    (work / 'dex.log').write_text(result.stdout + result.stderr)
    result.check_returncode()
    assert sha(source) == source_hash
    receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), passed=True,
                   source_sha256=source_hash, jar_sha256=sha(jar), sdk_sha256=sha(sdk), d8_sha256=sha(r8),
                   commands=[list(map(str, command)), list(map(str, dex))], ninja_graph_loaded=False,
                   camera_used=False, display_used=False, microphone_used=False, playback_used=False)
    (work / 'build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(dict(passed=True, jar=str(jar))))


if __name__ == '__main__':
    main()
