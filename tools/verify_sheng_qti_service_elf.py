#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check QTI bootstrap/payload dependencies and alignment without loading a build graph."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess

from build_sheng_qti_bootstrap_candidate import sha


def verify(rom, builds, work):
    work.mkdir(parents=True, exist_ok=False)
    checks = []
    for build in builds:
        for kind, output in build['outputs'].items():
            binary = Path(output['path'])
            assert sha(binary) == output['sha256']
            link = build['commands'][kind][1]
            response = next(arg[1:] for arg in link if arg.startswith('@'))
            libraries = {Path(arg).name: rom / arg for arg in shlex.split(Path(response).read_text())
                         if arg.endswith('.so')}
            assert set(output['needed']) <= set(libraries)
            command = ['python3', str(rom / 'build/make/tools/check_elf_file.py'),
                       '--llvm-readobj', str(rom / 'prebuilts/clang/host/linux-x86/clang-r596125/bin/llvm-readobj'),
                       '--max-page-size', '16384']
            for name in output['needed']:
                library = libraries[name]
                assert build['input_sha256'][str(library)] == sha(library)
                command += ['--shared-lib', str(library)]
            if kind == 'payload':
                command += ['--soname', binary.name]
            command.append(str(binary))
            result = subprocess.run(command, capture_output=True, text=True, timeout=55)
            (work / (build['profile'] + '-' + kind + '.log')).write_text(result.stdout + result.stderr)
            checks.append(dict(profile=build['profile'], kind=kind, command=command,
                               output_sha256=output['sha256'], exit_code=result.returncode))
    receipt = dict(passed=all(row['exit_code'] == 0 for row in checks), checks=checks, ninja_graph_loaded=False)
    (work / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    if not receipt['passed']:
        raise ValueError('The normal ELF checker rejected a service output; see ' + str(work))
    return work / 'receipt.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--build', type=Path, action='append', required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    builds = [json.loads(path.read_text()) for path in args.build]
    print(verify(args.rom.resolve(strict=True), builds, args.work.resolve()))


if __name__ == '__main__':
    main()
