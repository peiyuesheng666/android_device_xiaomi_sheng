#!/usr/bin/env python3
"""Match embedded host validation bytecode to its actual public source inputs."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import _imp
import json
import marshal
from pathlib import Path
import subprocess
import sys
import zipfile

# These are source inputs of the selected Soong libraries. ota_metadata_pb2
# is generated from ota_metadata.proto, not the checked-in Python file of the
# same name; comparing by basename would incorrectly reject a normal build.
SOURCE_MODULES = {
    'validate_target_files': {
        name: 'build/make/tools/releasetools/' + name + '.py' for name in
        ('validate_target_files', 'blockimgdiff', 'common', 'images', 'rangelib', 'sparse_img')},
    'check_target_files_vintf': {
        name: 'build/make/tools/releasetools/' + name + '.py' for name in
        ('check_target_files_vintf', 'apex_utils', 'blockimgdiff', 'common', 'images', 'rangelib', 'sparse_img')},
    'avbtool': {'avbtool': 'external/avb/avbtool.py'},
    'img_from_target_files': {
        name: 'build/make/tools/releasetools/' + name + '.py' for name in
        ('img_from_target_files', 'blockimgdiff', 'common', 'images', 'rangelib', 'sparse_img')},
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check_bytecode(data, source, filename):
    if len(data) < 16 or data[:4] != importlib.util.MAGIC_NUMBER:
        raise ValueError('Use the normal build Python runtime for this bytecode version')
    if int.from_bytes(data[4:8], 'little') != 3:
        raise ValueError('Expected the normal Soong checked-hash bytecode format')
    if data[8:16] != _imp.source_hash(int.from_bytes(data[:4], 'little'), source):
        raise ValueError('Embedded source hash differs from the selected source input')
    original = marshal.loads(data[16:])
    compiled = compile(source, filename, 'exec', dont_inherit=True, optimize=0)
    if original != compiled or original.co_filename != filename:
        raise ValueError('Embedded bytecode body differs from a fresh compilation of the source input')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rom = args.rom.resolve(strict=True)
    # Ubuntu's system Python uses an older hash algorithm and bytecode format.
    # Use the same provisioned runtime as Soong, without rebuilding any tool.
    if sys.version_info[:2] != (3, 13):
        subprocess.run([rom / 'prebuilts/build-tools/linux-x86/bin/py3-cmd',
                        Path(__file__).resolve(), '--rom', rom, '--output', args.output.resolve()], check=True)
        return
    report = dict(date_utc=datetime.now(timezone.utc).isoformat(), python=sys.version,
                  scope='Selected validation Python source modules; generated proto, runtime and native dependencies are outside this audit',
                  tools={}, module_count=0, passed=False)
    for tool, modules in SOURCE_MODULES.items():
        path = rom / 'out/host/linux-x86/bin' / tool
        result = dict(path=str(path), sha256=sha(path.read_bytes()), modules={}, passed=True)
        with zipfile.ZipFile(path) as archive:
            for name, relative in modules.items():
                source = (rom / relative).read_bytes()
                data = archive.read(name + '.pyc')
                entry = dict(source=relative, source_sha256=sha(source),
                             bytecode_sha256=sha(data), passed=False)
                try:
                    check_bytecode(data, source, name + '.py')
                    entry['passed'] = True
                except Exception as error:
                    entry['error'] = str(error)
                    result['passed'] = False
                result['modules'][name] = entry
                report['module_count'] += 1
        report['tools'][tool] = result
    report['passed'] = all(result['passed'] for result in report['tools'].values())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f'Host validation Python source audit: {report["module_count"]} modules, passed={report["passed"]}')
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
