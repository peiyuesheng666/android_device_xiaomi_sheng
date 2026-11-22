#!/usr/bin/env python3
"""Build an isolated QTI factory probe with the normal source service's flags."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path,
                        default=Path('/root/sheng-lineage/lineage-24.0'))
    parser.add_argument('--work', type=Path,
                        default=Path('/root/sheng-lineage/hardware-diagnostics/qti-factory-r60'))
    parser.add_argument('--diagnose-exit', action='store_true',
                        help='Diagnostic-only probe without seccomp, for abort backtraces')
    args = parser.parse_args()
    rom = args.rom.resolve()
    device = Path(__file__).resolve().parents[1]
    work = args.work.resolve()
    assert device == rom / 'device/xiaomi/sheng', (device, rom)
    module = 'sheng-vendor.qti.media.c2@1.0-service'
    service = 'vendor.qti.media.c2@1.0-service'
    base = rom / 'out/soong/.intermediates/device/xiaomi/sheng/interfaces/compat/codec2'
    candidates = list((base / module).glob('android_vendor_*/' + service))
    assert len(candidates) == 1, candidates
    target = candidates[0]
    assert target.is_file(), 'Build the normal QTI source service before this probe'
    commands = subprocess.check_output([
        rom / 'prebuilts/build-tools/linux-x86/bin/ninja', '-f',
        'out/combined-lineage_sheng.ninja', '-t', 'commands', target.relative_to(rom)
    ], cwd=rom, text=True).splitlines()
    source = 'device/xiaomi/sheng/interfaces/compat/codec2/qti_service.cpp'
    compile_lines = [line for line in commands if line.endswith(' ' + source)]
    link_lines = [line for line in commands if 'clang++ ' in line
                  and '/' + module + '/' in line and ' -c ' not in line]
    assert len(compile_lines) == len(link_lines) == 1
    work.mkdir(parents=True, exist_ok=True)
    compile_args = shlex.split(compile_lines[0])
    assert compile_args.pop(0) == 'PWD=/proc/self/cwd'
    original_object = compile_args[compile_args.index('-o') + 1]
    compile_args[compile_args.index('-o') + 1] = str(work / 'probe.o')
    compile_args[compile_args.index('-MF') + 1] = str(work / 'probe.d')
    compile_args[-1] = str(device / 'tools/ShengQtiCodec2FactoryProbe.cpp')
    if args.diagnose_exit:
        compile_args.insert(compile_args.index('-c'), '-DSHENG_QTI_FACTORY_DIAGNOSE_EXIT')
    link_args = shlex.split(link_lines[0])
    if args.diagnose_exit:
        link_args.append('-Wl,--export-dynamic-symbol=__cxa_atexit')
    responses = [arg for arg in link_args if arg.startswith('@')]
    assert len(responses) == 1
    response_args = shlex.split((rom / responses[0][1:]).read_text())
    assert response_args.count(original_object) == 1
    response_args[response_args.index(original_object)] = str(work / 'probe.o')
    response = work / 'probe.rsp'
    response.write_text(shlex.join(response_args) + '\n')
    link_args[link_args.index(responses[0])] = '@' + str(response)
    output = work / 'sheng-qti-codec2-factory-probe'
    link_args[link_args.index('-o') + 1] = str(output)
    # The compiler and linker run unchanged except for the diagnostic source,
    # object, dependency file, response file and output paths.
    receipt = {
        'service': str(target), 'service_sha256': sha256(target),
        'service_source_sha256': sha256(rom / source),
        'probe_source_sha256': sha256(device / 'tools/ShengQtiCodec2FactoryProbe.cpp'),
        'commands': [compile_args, link_args],
        'runtime_scope': 'temporary OEM factory/listComponents only; no HAL registration',
        'runtime_validation': 'not run by this builder',
        'seccomp_enabled': not args.diagnose_exit,
    }
    (work / 'commands.json').write_text(json.dumps(receipt, indent=2) + '\n')
    subprocess.run(compile_args, cwd=rom, check=True)
    subprocess.run(link_args, cwd=rom, check=True)
    receipt['output'] = str(output)
    receipt['output_sha256'] = sha256(output)
    receipt['build'] = 'compiled and linked with normal source service flags'
    (work / 'build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
