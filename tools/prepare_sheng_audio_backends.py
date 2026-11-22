#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Restore the stock audio decoder libraries omitted from proprietary extraction."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import re
import shutil
import subprocess

from build_sheng_qti_bootstrap_candidate import sha


def module_text(module, relative, needed):
    libraries = ''.join('                "' + name.removesuffix('.so') + '",\n' for name in needed)
    return ('cc_prebuilt_library_shared {\n'
            '    name: "' + module + '",\n'
            '    owner: "xiaomi",\n'
            '    strip: { none: true },\n'
            '    target: {\n'
            '        android_arm64: {\n'
            '            srcs: ["proprietary/vendor/' + relative + '"],\n'
            '            shared_libs: [\n' + libraries + '            ],\n'
            '        },\n'
            '    },\n'
            '    compile_multilib: "64",\n'
            '    prefer: true,\n'
            '    soc_specific: true,\n'
            '}\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--firmware', type=Path, required=True, help='Original extracted partition root')
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--link-build', type=Path, required=True, help='Recorded targeted service linker inputs')
    args = parser.parse_args()
    rom = args.rom.resolve(strict=True)
    source = Path(__file__).resolve().parents[1]
    catalog = json.loads((source / 'configs/audio-codec-backends.json').read_text())
    assert catalog['partition'] == 'vendor' and catalog['architecture'] == 'arm64'
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    assert work.stat().st_dev == Path('/').stat().st_dev
    lock = (rom / 'out/.sheng-device-modules.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    vendor = rom / 'vendor/xiaomi/sheng'
    bp = vendor / 'Android.bp'
    mk = vendor / 'sheng-vendor.mk'
    before_bp, before_mk = bp.read_text(), mk.read_text()
    proposed_bp, proposed_mk = before_bp, before_mk
    entries, checks, dependency_hashes = {}, [], {}
    linked = json.loads(args.link_build.read_text())
    assert linked['compiled'] and linked['seccomp_enabled']
    link_libraries = {Path(name).name: Path(name) for name in linked['input_sha256'] if name.endswith('.so')}
    readelf = rom / 'prebuilts/clang/host/linux-x86/clang-r596125/bin/llvm-readelf'
    proprietary = set((source / 'proprietary-files.txt').read_text().splitlines())
    for item in catalog['libraries']:
        relative = item['path']
        assert re.fullmatch(r'lib64/lib[A-Za-z0-9]+\.so', relative)
        assert 'vendor/' + relative in proprietary
        original = args.firmware.resolve(strict=True) / 'vendor' / relative
        assert sha(original) == item['sha256']
        target = work / 'vendor' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        assert sha(target) == item['sha256']
        elf = subprocess.check_output([readelf, '-h', '-d', target], text=True)
        assert re.search(r'Machine:\s+AArch64', elf)
        assert 'Library soname: [' + target.name + ']' in elf
        needed = re.findall(r'Shared library: \[(.*?)\]', elf)
        assert set(needed) == {'liblog.so', 'libc++.so', 'libc.so', 'libm.so', 'libdl.so'}
        command = ['python3', str(rom / 'build/make/tools/check_elf_file.py'),
                   '--llvm-readobj', str(readelf.with_name('llvm-readobj')),
                   '--max-page-size', '4096', '--soname', target.name]
        for name in needed:
            library = link_libraries[name]
            assert library.is_file() and sha(library) == linked['input_sha256'][str(library)]
            dependency_hashes[str(library)] = sha(library)
            command += ['--shared-lib', str(library)]
        command.append(str(target))
        result = subprocess.run(command, capture_output=True, text=True, timeout=55)
        (work / (item['module'] + '-elf.log')).write_text(result.stdout + result.stderr)
        checks.append(dict(library=target.name, command=command, exit_code=result.returncode,
                           output_sha256=item['sha256'], max_page_size=4096))
        result.check_returncode()
        entries[relative] = dict(source=str(target), original=str(original),
                                 bytes=target.stat().st_size, sha256=item['sha256'])
        marker = '    name: "' + item['module'] + '",'
        if marker not in proposed_bp:
            proposed_bp += '\n' + module_text(item['module'], relative, needed)
        else:
            assert proposed_bp.count(marker) == 1
            start = proposed_bp.index(marker)
            end = proposed_bp.index('\n}\n', start)
            assert '"proprietary/vendor/' + relative + '"' in proposed_bp[start:end]
        if not re.search(r'^(?:    |PRODUCT_PACKAGES \+= )' + re.escape(item['module']) + r'(?: \\)?$', proposed_mk, re.M):
            proposed_mk += '\nPRODUCT_PACKAGES += ' + item['module'] + '\n'
    for name, before, proposed in (('Android.bp', before_bp, proposed_bp), ('sheng-vendor.mk', before_mk, proposed_mk)):
        (work / ('before-' + name)).write_text(before)
        (work / ('proposed-' + name)).write_text(proposed)
    for relative, entry in entries.items():
        target = vendor / 'proprietary/vendor' / relative
        assert not target.exists() or sha(target) == entry['sha256']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(entry['source'], target)
        assert sha(target) == entry['sha256']
    assert bp.read_text() == before_bp and mk.read_text() == before_mk
    bp.write_text(proposed_bp)
    mk.write_text(proposed_mk)
    receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), passed=True,
                   unchanged_oem_bytes=True, entries=entries, checks=checks,
                   dependencies_sha256=dependency_hashes, ninja_graph_loaded=False,
                   normal_module_build_passed=False, installed=False,
                   source_sha256={name: sha(source / name) for name in (
                       'configs/audio-codec-backends.json', 'proprietary-files.txt',
                       'interfaces/compat/codec2/Android.bp', 'tools/prepare_sheng_audio_backends.py')},
                   generated_sha256={str(bp): sha(bp), str(mk): sha(mk)})
    (work / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(work / 'receipt.json')


if __name__ == '__main__':
    main()
