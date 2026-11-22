#!/usr/bin/env python3
"""Compile an uninstalled QTI loader/payload using existing normal build flags."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import re
import resource
import shlex
import subprocess

BOOTSTRAP_LIBS = {
    'libavservices_minijail.so', 'libdl.so', 'liblog.so', 'libc++.so', 'libc.so', 'libm.so',
}
SOURCES = ('Android.bp', 'qti_bootstrap.cpp', 'qti_payload.cpp',
           'qti_load_groups.h', 'qti_profile.h', 'qti_service.cpp',
           'qti_alac_config.h', 'qti_audio_store.h')
PROFILES = {
    'video': dict(bootstrap='sheng-qti-codec2-bootstrap', payload='libsheng_qti_codec2_service.so',
                  service='vendor.qti.media.c2@1.0-service', instance='default',
                  core='libqcodec2_core.so', policy_prefix='codec2', component_count=19,
                  components=('c2.qti.avc.decoder', 'c2.qti.hevc.encoder')),
    'audio': dict(bootstrap='sheng-qti-audio-codec2-bootstrap', payload='libsheng_qti_audio_codec2_service.so',
                  service='vendor.qti.media.c2audio@1.0-service', instance='default2',
                  core='libqc2audio_core.so', policy_prefix='c2audio', component_count=17,
                  components=('c2.qti.flac.sw.decoder', 'c2.qti.aac.hw.decoder', 'c2.qti.aac.hw.encoder',
                              'c2.qti.alac.sw.decoder', 'c2.qti.alac.hw.decoder')),
}


def profile_libraries(source, profile):
    text = (source / 'qti_load_groups.h').read_text()
    choices = text.split('#if defined(SHENG_QTI_AUDIO)', 1)[1].split('#endif', 1)[0].split('#else')
    selected = choices[0 if profile == 'audio' else 1]
    return re.findall(r'"(lib[^"\n]+\.so)"', selected)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--factory-build', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--profile', choices=PROFILES, default='video')
    parser.add_argument('--frame-probe', action='store_true',
                        help='Compile the isolated tool extension, leaving product sources unchanged')
    parser.add_argument('--pool-probe', action='store_true',
                        help='Compile the isolated audio HIDL pool ownership diagnostic')
    parser.add_argument('--qualify-targeted', action='store_true',
                        help='Record current source, headers and linker inputs for a targeted device package')
    parser.add_argument('--preaudit', type=Path,
                        help='Successful current public-source audit for targeted qualification')
    args = parser.parse_args()
    profile = PROFILES[args.profile]
    if args.frame_probe and args.profile != 'video':
        parser.error('The frame diagnostic only supports video')
    if args.pool_probe and (args.profile != 'audio' or args.frame_probe):
        parser.error('The pool diagnostic only supports audio')
    diagnostic_kind = 'frame' if args.frame_probe else 'pool' if args.pool_probe else None
    rom = args.rom.resolve(strict=True)
    if args.qualify_targeted and (diagnostic_kind or args.preaudit is None):
        parser.error('Targeted qualification requires a public-source audit and the production sources')
    lock = (rom / 'out/.sheng-device-modules.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    audit = None
    if args.qualify_targeted:
        audit = json.loads(args.preaudit.read_text())
        assert audit['passed'] and all(row['passed'] for row in audit['repositories'])
        required_repos = {'frameworks/av', 'frameworks/native', 'system/core', 'system/libhidl',
                          'bionic', 'build/soong', 'external/minijail'}
        assert required_repos <= {row['path'] for row in audit['repositories']}
        for row in audit['repositories']:
            head = subprocess.check_output(['git', '-C', str(rom / row['path']), 'rev-parse', 'HEAD'],
                                           text=True).strip()
            assert head == row['head']
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parents[1] / 'interfaces/compat/codec2'
    prior = json.loads((args.factory_build / 'build.json').read_text())
    assert prior.get('seccomp_enabled') is not False
    assert not any('DIAGNOSE_EXIT' in arg or '__cxa_atexit' in arg
                   for command in prior['commands'] for arg in command)
    assert sha(Path(prior['service'])) == prior['service_sha256']
    original_compile, original_link = prior['commands']
    response_arg = next(arg for arg in original_link if arg.startswith('@'))
    old_response = shlex.split(Path(response_arg[1:]).read_text())
    compiler = rom / 'prebuilts/clang/host/linux-x86/clang-r596125/bin/clang++'
    sources = {name: sha(source / name) for name in SOURCES}
    diagnostic = Path(__file__).resolve().parent
    diagnostic_sources = {name: sha(diagnostic / name) for name in
                          ('qti_' + diagnostic_kind + '_bootstrap.cpp',
                           'qti_' + diagnostic_kind + '_payload.cpp')} if diagnostic_kind else {}
    receipt = dict(source_hashes=sources, original_flags_receipt=str(args.factory_build),
                   product_integrated=False, normal_module_build_passed=False,
                   seccomp_enabled=True, compiled=False, commands={}, outputs={})
    receipt.update(frame_diagnostic=args.frame_probe, pool_diagnostic=args.pool_probe,
                   diagnostic_source_hashes=diagnostic_sources)
    receipt['profile'] = args.profile
    receipt.update(targeted_module_build_passed=False, ninja_graph_loaded=False,
                   compiler_sha256=sha(compiler), builder_sha256=sha(Path(__file__)),
                   original_flags_receipt_sha256=sha(args.factory_build / 'build.json'),
                   original_response_file=response_arg[1:], original_response_sha256=sha(Path(response_arg[1:])),
                   input_sha256={})
    if audit:
        receipt.update(preaudit=str(args.preaudit.resolve()), preaudit_sha256=sha(args.preaudit))
    # The explicit C-backed policy check never starts a global build.
    subprocess.run(['python3', str(source.parents[2] / 'tools/prepare_sheng_stylus_swap.py'),
                    '--work', str(work)], check=True, stdout=subprocess.DEVNULL)
    for kind, filename, output_name in (
            ('bootstrap', 'qti_bootstrap.cpp', profile['bootstrap']),
            ('payload', 'qti_payload.cpp', profile['payload'])):
        compile_args = list(original_compile)
        if Path(compile_args[0]).name == 'ccache': compile_args.pop(0)
        assert rom / compile_args[0] == compiler
        compile_args[-1] = str(diagnostic / ('qti_' + diagnostic_kind + '_' + kind + '.cpp')
                               if diagnostic_kind else source / filename)
        compile_args[compile_args.index('-o') + 1] = str(work / (kind + '.o'))
        compile_args[compile_args.index('-MF') + 1] = str(work / (kind + '.d'))
        if args.profile == 'audio':
            compile_args.insert(compile_args.index('-c'), '-DSHENG_QTI_AUDIO')
        link_args = list(original_link)
        response = [str(work / (kind + '.o'))]
        for arg in old_response:
            if arg.endswith('.o'): continue
            if kind == 'payload':
                if Path(arg).name == 'libavservices_minijail.so': continue
                response.append(arg)
            elif (Path(arg).name in BOOTSTRAP_LIBS or Path(arg).name in (
                    'libc++demangle.a', 'libclang_rt.builtins-aarch64-android.a')):
                response.append(arg)
        if kind == 'payload':
            compile_args = [arg for arg in compile_args if arg not in ('-fPIE', '-fpie')]
            compile_args.insert(compile_args.index('-c'), '-fPIC')
            link_args = [arg for arg in link_args if arg not in (
                '-pie', '-Wl,-dynamic-linker,/system/bin/linker64')]
            link_args += ['-shared', '-Wl,-soname,' + output_name]
            for i, arg in enumerate(link_args):
                if 'crtbegin_dynamic/' in arg:
                    link_args[i] = arg.replace('crtbegin_dynamic/', 'crtbegin_so/').replace(
                        '/crtbegin_dynamic.o', '/crtbegin_so.o')
                elif 'crtend_android/' in arg:
                    link_args[i] = arg.replace('crtend_android/', 'crtend_so/').replace(
                        '/crtend_android.o', '/crtend_so.o')
            assert all((rom / arg).is_file() for arg in link_args if arg.endswith('.o'))
        rsp = work / (kind + '.rsp')
        rsp.write_text(shlex.join(response) + '\n')
        link_args[link_args.index(response_arg)] = '@' + str(rsp)
        output = work / output_name
        link_args[link_args.index('-o') + 1] = str(output)
        link_args.append('-Wl,--threads=1')
        receipt['commands'][kind] = [compile_args, link_args]
        for arg in [*response, *link_args]:
            if arg.startswith('-') or arg.startswith('@'):
                continue
            path = rom / arg
            if path.is_file() and path.suffix in ('.a', '.o', '.so'):
                receipt['input_sha256'][str(path)] = sha(path)
        (work / 'commands.json').write_text(json.dumps(receipt, indent=2) + '\n')
        for stage, command in [('compile', compile_args), ('link', link_args)]:
            if args.frame_probe:
                powershell = '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
                headroom = int(subprocess.check_output([powershell, '-NoProfile', '-NonInteractive',
                    '-Command', '(Get-CimInstance Win32_OperatingSystem).FreeVirtualMemory'],
                    text=True, timeout=30).strip()) * 1024
                if headroom < 5 * 1024**3:
                    raise RuntimeError('Frame diagnostic compile requires 5 GiB host commit headroom')
            def bound_diagnostic():
                resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024**2, 1536 * 1024**2))
            with (work / (kind + '-' + stage + '.log')).open('wb') as log:
                subprocess.run(command, cwd=rom, stdout=log, stderr=subprocess.STDOUT, check=True,
                               preexec_fn=bound_diagnostic if args.frame_probe else None)
        dynamic = subprocess.check_output([compiler.with_name('llvm-readelf'), '-d', output], text=True)
        needed = re.findall(r'Shared library: \[(.*?)\]', dynamic)
        if kind == 'bootstrap': assert set(needed) <= BOOTSTRAP_LIBS, needed
        if kind == 'payload':
            assert 'Library soname: [' + output_name + ']' in dynamic
            assert {'libcodec2_vndk.so', 'libcodec2_hidl@1.0.so'} <= set(needed)
        (work / (kind + '-elf.txt')).write_text(dynamic)
        dependencies = (work / (kind + '.d')).read_text().replace('\\\n', ' ')
        for dependency in shlex.split(dependencies.split(':', 1)[1]):
            path = rom / dependency
            assert path.is_file(), path
            receipt['input_sha256'][str(path)] = sha(path)
        receipt['outputs'][kind] = dict(path=str(output), sha256=sha(output), needed=needed)
    for name, digest in sources.items(): assert sha(source / name) == digest, name
    for name, digest in receipt['input_sha256'].items(): assert sha(Path(name)) == digest, name
    if args.qualify_targeted:
        assert not any('DIAGNOSE_EXIT' in arg or '__cxa_atexit' in arg
                       for commands in receipt['commands'].values() for command in commands for arg in command)
        receipt['targeted_module_build_passed'] = True
    receipt['compiled'] = True
    (work / 'build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt['outputs'], indent=2))


if __name__ == '__main__':
    main()
