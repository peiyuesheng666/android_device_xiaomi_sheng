#!/usr/bin/env python3
"""Build a temporary QTI load-group experiment without changing product outputs."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

PROVIDERS = (
    'libcodec2_vndk.so', 'libqcodec2_v4l2codec.so',
    'libqcodec2_filterbase.so', 'libqc2audio_basecodec.so',
    'libqc2filter.so', 'libqc2colorconvertfilter.so', 'libqc2vppfilter.so',
)
DIRECT_LIBRARIES = {
    'libavservices_minijail.so', 'libbinder.so', 'libhidlbase.so', 'liblog.so',
    'libutils.so', 'libdl.so', 'libc++.so', 'libc.so', 'libm.so',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(path, readelf):
    output = subprocess.check_output(
        [readelf, '--dyn-syms', '--relocs', '--wide', path], text=True)
    definitions, relocations = {}, {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 8 and fields[0].endswith(':') and fields[0][:-1].isdigit():
            name = fields[7].split('@', 1)[0]
            if name.endswith('11_FIELD_LISTE') and fields[6] != 'UND':
                assert fields[3:6] == ['OBJECT', 'GLOBAL', 'DEFAULT'], line
                definitions[name] = int(fields[1], 16)
        if len(fields) >= 5 and fields[2].startswith('R_AARCH64_'):
            name = fields[4].split('@', 1)[0]
            if name.endswith('11_FIELD_LISTE'):
                assert fields[2] == 'R_AARCH64_GLOB_DAT', line
                assert name not in relocations, name
                relocations[name] = int(fields[0], 16)
    assert definitions and definitions.keys() == relocations.keys(), path
    return [dict(name=name, value=value, relocation=relocations[name])
            for name, value in sorted(definitions.items())]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--factory-build', type=Path, required=True,
                        help='Existing normal-flags factory probe build receipt directory')
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    rom = args.rom.resolve(strict=True)
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).with_name('ShengQtiLoadGroupsProbe.cpp')
    prior = json.loads((args.factory_build / 'build.json').read_text())
    assert prior.get('seccomp_enabled') is not False, 'Unsandboxed diagnostic build'
    assert not any('DIAGNOSE_EXIT' in arg or '__cxa_atexit' in arg
                   for command in prior['commands'] for arg in command), \
        'Do not inherit sandbox bypasses or finalizer tracing flags'
    service = rom / 'device/xiaomi/sheng/interfaces/compat/codec2/qti_service.cpp'
    assert sha(service) == prior['service_source_sha256']
    assert sha(Path(prior['service'])) == prior['service_sha256']
    compiler = rom / 'prebuilts/clang/host/linux-x86/clang-r596125/bin/clang++'
    readelf = compiler.with_name('llvm-readelf')
    header, inputs = [], []
    for i, library in enumerate(PROVIDERS):
        path = (rom / 'out/target/product/sheng/vendor/lib64' / library
                if library == 'libcodec2_vndk.so' else
                rom / 'vendor/xiaomi/sheng/proprietary/vendor/lib64' / library)
        fields = inspect(path, readelf)
        inputs.append(dict(library=library, path=str(path), sha256=sha(path), fields=fields))
        header.append(f'static const FieldBinding kFields{i}[] = {{')
        for field in fields:
            header.append('    {%s, 0x%x, 0x%x},' % (
                json.dumps(field['name']), field['value'], field['relocation']))
        header.append('};')
    header.append('static const Provider kProviders[] = {')
    for i, entry in enumerate(inputs):
        header.append('    {%s, kFields%d, %d},' % (
            json.dumps(entry['library']), i, len(entry['fields'])))
    header.append('};')
    (work / 'qti-field-bindings.h').write_text('\n'.join(header) + '\n')
    compile_args, link_args = [list(command) for command in prior['commands']]
    if Path(compile_args[0]).name == 'ccache':
        compile_args.pop(0)
    assert rom / compile_args[0] == compiler
    compile_args[compile_args.index('-o') + 1] = str(work / 'probe.o')
    compile_args[compile_args.index('-MF') + 1] = str(work / 'probe.d')
    compile_args[-1] = str(source)
    compile_args.insert(compile_args.index('-c'), '-I' + str(work))
    old_response = next(arg for arg in link_args if arg.startswith('@'))
    response_args = shlex.split(Path(old_response[1:]).read_text())
    # This executable must not load C2 providers through its startup DT_NEEDED
    # group. Keep the standard C runtime and the original sandbox/binder APIs.
    new_response = [str(work / 'probe.o')]
    for arg in response_args:
        name = Path(arg).name
        if name in DIRECT_LIBRARIES or name in (
                'libc++demangle.a', 'libclang_rt.builtins-aarch64-android.a'):
            new_response.append(arg)
    assert {Path(arg).name for arg in new_response} >= DIRECT_LIBRARIES
    response = work / 'probe.rsp'
    response.write_text(shlex.join(new_response) + '\n')
    link_args[link_args.index(old_response)] = '@' + str(response)
    output = work / 'sheng-qti-load-groups-probe'
    link_args[link_args.index('-o') + 1] = str(output)
    link_args.append('-Wl,--threads=1')
    receipt = dict(source=str(source), source_sha256=sha(source),
                   inputs=inputs, commands=[compile_args, link_args],
                   original_probe_build=str(args.factory_build),
                   seccomp_enabled=True, hal_registration=False,
                   product_integrated=False, runtime_tested=False)
    (work / 'commands.json').write_text(json.dumps(receipt, indent=2) + '\n')
    for i, command in enumerate((compile_args, link_args)):
        with (work / ('compile.log' if i == 0 else 'link.log')).open('wb') as log:
            subprocess.run(command, cwd=rom, stdout=log, stderr=subprocess.STDOUT, check=True)
    dynamic = subprocess.check_output([readelf, '-d', output], text=True)
    needed = re.findall(r'Shared library: \[(.*?)\]', dynamic)
    assert set(needed) <= DIRECT_LIBRARIES, needed
    assert not any('codec2' in name for name in needed)
    receipt.update(output=str(output), output_sha256=sha(output), needed=needed,
                   compiled=True, binding_count=sum(len(i['fields']) for i in inputs))
    (work / 'build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k: receipt[k] for k in ('output', 'output_sha256', 'needed', 'binding_count')}, indent=2))


if __name__ == '__main__':
    main()
