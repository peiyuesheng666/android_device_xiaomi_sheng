#!/usr/bin/env python3
"""Check the final linked pystore kernel, including replaying its logger compile.

This does not qualify external modules, images, AVB, SELinux or runtime behavior.
Run only after the matched module build has finalized Image and its BTF base.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

from sheng_kernel_image import qualify, sha

REQUIRED = {'finish_boot', 'boot_complete', 'pystore_ops', 'pystore_open',
            'pystore_read', 'snapshot_thread'}


def symbols(tool, path):
    output = subprocess.check_output([str(tool), '--defined-only', str(path)],
                                     text=True, timeout=120)
    names = {line.split()[-1] for line in output.splitlines() if line.split()}
    if not REQUIRED <= names:
        raise ValueError('Missing pystore identity symbols: ' + repr(sorted(REQUIRED - names)))
    return sorted(REQUIRED)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-out', type=Path, required=True)
    parser.add_argument('--clang-bin', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    core = args.kernel_out.resolve(strict=True)
    clang = args.clang_bin.resolve(strict=True)
    if args.out.exists():
        raise ValueError('Preserve existing qualification output; use a new path')
    config = (core / '.config').read_text().splitlines()
    for value in ('CONFIG_SHENG_BOOTLOG=y', 'CONFIG_LOG_BUF_SHIFT=22',
                  'CONFIG_MODVERSIONS=y', 'CONFIG_SECURITY_SELINUX=y',
                  'CONFIG_PROC_FS=y', 'CONFIG_LTO_NONE=y'):
        if value not in config:
            raise ValueError('Unexpected core config: ' + value)
    final = qualify(core, clang / 'llvm-objcopy')
    obj = core / 'drivers/misc/sheng_bootlog.o'
    before = {name: sha(core / name) for name in
              ('vmlinux', 'drivers/misc/sheng_bootlog.o', '.config', 'Module.symvers')}
    saved = (core / 'drivers/misc/.sheng_bootlog.o.cmd').read_text().splitlines()[0]
    key, command = saved.split(' := ', 1)
    if key.strip() != 'savedcmd_drivers/misc/sheng_bootlog.o':
        raise ValueError('Unknown logger compiler command')
    argv = shlex.split(command)
    if argv[0] != 'clang' or argv.count('-o') != 1 or '-c' not in argv:
        raise ValueError('Expected a direct clang compile, not a shell recipe')
    if any(token in (';', '&&', '|', '||') for token in argv):
        raise ValueError('Unsupported compound compiler command')
    source = Path(argv[-1]).resolve(strict=True)
    owned = Path(__file__).resolve().parents[1] / 'interfaces/kernel/6.18/sheng_bootlog.c'
    if sha(source) != sha(owned):
        raise ValueError('Built source differs from device-owned pystore')
    argv[0] = str(clang / 'clang')
    env = dict(os.environ, PATH=str(clang) + ':' + os.environ.get('PATH', ''))
    with tempfile.TemporaryDirectory(prefix='sheng-pystore-replay-') as temp:
        replay = Path(temp) / 'sheng_bootlog.o'
        argv[argv.index('-o') + 1] = str(replay)
        argv = ['-Wp,-MMD,' + str(Path(temp) / 'logger.d')
                if token.startswith('-Wp,-MMD,') else token for token in argv]
        subprocess.run(argv, cwd=core, env=env, check=True, timeout=120,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if sha(replay) != sha(obj):
            raise ValueError('Replayed current logger is not byte-identical to built object')
    identities = {label: symbols(clang / 'llvm-nm', path)
                  for label, path in [('object', obj), ('vmlinux', core / 'vmlinux')]}
    if before != {name: sha(core / name) for name in before}:
        raise ValueError('Kernel changed during qualification; wait for build completion')
    result = dict(passed=True, scope='offline final pystore kernel only',
                  logger_source_sha256=sha(source), artifacts_sha256=before,
                  final_kernel_image=final, identity_symbols=identities,
                  current_source_compile_replayed_byte_identical=True,
                  logger_identity_verified_in_object_and_vmlinux=True,
                  pystore_boot_only_verified_in_object_and_vmlinux=True,
                  external_modules_qualified=False, packaged_images=False,
                  runtime_verified=False, rawdump_preservation_runtime_verified=False,
                  flashed=False)
    with args.out.open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
