#!/usr/bin/env python3
"""Record the exact uninstalled QTI pair from a completed normal Soong build."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

from build_sheng_qti_bootstrap_candidate import BOOTSTRAP_LIBS, PROFILES, SOURCES, sha

def profile_modules(profile_name):
    profile = PROFILES[profile_name]
    return {
        'bootstrap': (profile['bootstrap'], profile['bootstrap'], 'qti_bootstrap.cpp'),
        'payload': (profile['payload'].removesuffix('.so'), profile['payload'], 'qti_payload.cpp'),
    }


def completed_normal_build(run, profile_name='video'):
    status = json.loads((run / 'status.json').read_text())
    if not (status['exit_code'] == 0 and status['normal_module_build_passed'] is True
            and status['postbuild_checks_completed'] is True and status['last_phase'] == 'complete'):
        raise ValueError('A completed normal module build with postbuild checks is required')
    if not {module for module, _, _ in profile_modules(profile_name).values()} <= set(status['modules']):
        raise ValueError('The successful build must include both QTI modules')
    for name in ('prebuild-upstream-audit.json', 'postbuild-upstream-audit.json'):
        audit = json.loads((run / name).read_text())
        if audit['known_public_sources_passed'] is not True or audit['all_project_nonclean_status']:
            raise ValueError('Failed normal-build public-source audit: ' + name)
    for name in ('prebuild-recovery-upstream-audit.json', 'source-mirror.json'):
        if json.loads((run / name).read_text())['passed'] is not True:
            raise ValueError('Failed normal-build check: ' + name)
    sync = json.loads((run / 'source-sync.json').read_text())
    for name in SOURCES:
        if 'interfaces/compat/codec2/' + name not in sync['files']:
            raise ValueError('Normal-build source synchronization omitted ' + name)
    return status, sync


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--normal-build', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--profile', choices=PROFILES, default='video')
    args = parser.parse_args()
    rom = args.rom.resolve(strict=True)
    build_lock = (rom / 'out/.sheng-device-modules.lock').open('a')
    try:
        fcntl.flock(build_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise ValueError('A live build owns the graph and outputs; wait for completion') from None
    run = args.normal_build.resolve(strict=True)
    status, sync = completed_normal_build(run, args.profile)
    modules = profile_modules(args.profile)
    source = Path(__file__).resolve().parents[1] / 'interfaces/compat/codec2'
    mirror = rom / 'device/xiaomi/sheng/interfaces/compat/codec2'
    hashes = {}
    for name in SOURCES:
        digest = sha(source / name)
        if digest != sha(mirror / name) or digest != sync['files']['interfaces/compat/codec2/' + name]['sha256']:
            raise ValueError('Source changed since the normal build: ' + name)
        hashes[name] = digest
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(),
                   normal_build=str(run), normal_build_status_sha256=sha(run / 'status.json'),
                   normal_module_build_passed=True, source_hashes=hashes,
                   seccomp_enabled=True, product_integrated=False, compiled=False,
                   outputs={}, commands={}, profile=args.profile)
    for name in ('status.json', 'source-sync.json', 'source-mirror.json',
                 'prebuild-upstream-audit.json', 'postbuild-upstream-audit.json',
                 'prebuild-recovery-upstream-audit.json'):
        shutil.copyfile(run / name, work / ('normal-' + name))
    readelf = rom / 'prebuilts/clang/host/linux-x86/clang-r596125/bin/llvm-readelf'
    base = rom / 'out/soong/.intermediates/device/xiaomi/sheng/interfaces/compat/codec2'
    binaries = {}
    targets = []
    for kind, (module, filename, cpp) in modules.items():
        candidates = list((base / module).glob('android_vendor_*/' + filename))
        if len(candidates) != 1 or not candidates[0].is_file():
            raise ValueError('Expected one normal vendor-arm64 output: ' + module)
        binary = candidates[0]
        objects = list((binary.parent / 'obj').rglob(Path(cpp).stem + '.o'))
        if len(objects) != 1 or not objects[0].is_file():
            raise ValueError('Expected one actual source object for command recording: ' + module)
        binaries[kind] = binary
        targets.extend([objects[0].relative_to(rom), binary.relative_to(rom)])
    # -s prints only each requested edge. Do not materialize every dependency's
    # commands or load the combined graph separately for each module.
    command = [rom / 'prebuilts/build-tools/linux-x86/bin/ninja', '-f',
               'out/combined-lineage_sheng.ninja', '-t', 'commands', '-s', *targets]
    cgroup = Path('/sys/fs/cgroup') / ('sheng-qti-command-recording-' + str(os.getpid()))
    if 'memory' not in (cgroup.parent / 'cgroup.controllers').read_text().split():
        raise ValueError('Guest memory controller is unavailable')
    if 'memory' not in (cgroup.parent / 'cgroup.subtree_control').read_text().split():
        (cgroup.parent / 'cgroup.subtree_control').write_text('+memory')
    cgroup.mkdir()
    try:
        (cgroup / 'memory.high').write_text(str(7 * 1024**3))
        (cgroup / 'memory.max').write_text(str(7 * 1024**3))
        (cgroup / 'memory.swap.max').write_text(str(20 * 1024**3))
        print('Recording four actual Ninja commands with bounded memory', flush=True)
        result = subprocess.run(command, cwd=rom, text=True, capture_output=True,
            timeout=600, preexec_fn=lambda: (cgroup / 'cgroup.procs').write_text(str(os.getpid())))
        (work / 'ninja-commands.txt').write_text(result.stdout)
        (work / 'ninja-commands.stderr').write_text(result.stderr)
        receipt['command_extraction'] = dict(argv=list(map(str, command)), exit_code=result.returncode,
            memory_max=7 * 1024**3, swap_max=20 * 1024**3,
            memory_events=(cgroup / 'memory.events').read_text(),
            single_edges=True, combined_graph_parse_count=1)
        result.check_returncode()
        commands = result.stdout.splitlines()
        if len(commands) != len(targets):
            raise ValueError('Expected exactly four compile/link commands')
    finally:
        if not (cgroup / 'cgroup.procs').read_text().strip(): cgroup.rmdir()
    for kind, (module, filename, cpp) in modules.items():
        binary = binaries[kind]
        own_commands = [line for line in commands if '/' + module + '/' in line and 'clang++ ' in line]
        compiles = [line for line in own_commands if line.endswith(' ' + str(mirror.relative_to(rom) / cpp))]
        links = [line for line in own_commands if ' -c ' not in line]
        if len(compiles) != 1 or len(links) != 1:
            raise ValueError('Cannot identify the actual normal compile and link commands: ' + module)
        if any('DIAGNOSE_EXIT' in line or '__cxa_atexit' in line for line in own_commands):
            raise ValueError('Diagnostic teardown overrides are forbidden')
        receipt['commands'][kind] = [shlex.split(compiles[0]), shlex.split(links[0])]
        elf = subprocess.check_output([readelf, '-h', '-d', binary], text=True)
        (work / (kind + '-elf.txt')).write_text(elf)
        if not re.search(r'Machine:\s+AArch64', elf):
            raise ValueError('QTI output is not AArch64')
        needed = re.findall(r'Shared library: \[(.*?)\]', elf)
        if kind == 'bootstrap' and not set(needed) <= BOOTSTRAP_LIBS:
            raise ValueError('Bootstrap startup pulls additional providers into the global group: ' + repr(needed))
        if kind == 'payload':
            if 'Library soname: [' + PROFILES[args.profile]['payload'] + ']' not in elf:
                raise ValueError('Payload SONAME differs from the bootstrap dlopen name')
            if not {'libcodec2_vndk.so', 'libcodec2_hidl@1.0.so'} <= set(needed):
                raise ValueError('Payload is missing its actual platform C2 dependencies')
        destination = work / filename
        shutil.copyfile(binary, destination)
        if sha(destination) != sha(binary):
            raise ValueError('Output changed while copying: ' + module)
        receipt['outputs'][kind] = dict(path=str(destination), sha256=sha(destination),
                                        normal_output=str(binary), needed=needed)
    receipt['compiled'] = True
    (work / 'commands.json').write_text(json.dumps(receipt['commands'], indent=2) + '\n')
    (work / 'build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt['outputs'], indent=2))


if __name__ == '__main__':
    main()
