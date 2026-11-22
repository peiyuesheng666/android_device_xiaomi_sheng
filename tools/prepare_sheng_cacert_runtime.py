#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Restore the stock certificate service's native runtime and generated modules."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import re
import shutil
import subprocess

from build_sheng_qti_bootstrap_candidate import sha
from postprocess_vendor import install_cacert_runtime
from prepare_sheng_audio_backends import module_text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--firmware', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--link-build', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    rom = args.rom.resolve(strict=True)
    source = Path(__file__).resolve().parents[1]
    catalog = json.loads((source / 'configs/cacert-runtime.json').read_text())
    assert catalog['partition'] == 'vendor' and catalog['architecture'] == 'arm64'
    baseline = json.loads(args.baseline.read_text())
    assert baseline['complete_avb_chain_verified']
    vendor_tree = Path(baseline['work_dir']) / 'vendor-tree'
    assert vendor_tree.is_dir()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    assert work.stat().st_dev == Path('/').stat().st_dev
    lock = (rom / 'out/.sheng-device-modules.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    vendor = rom / 'vendor/xiaomi/sheng'
    bp, mk = vendor / 'Android.bp', vendor / 'sheng-vendor.mk'
    before_bp, before_mk = bp.read_text(), mk.read_text()
    proposed_bp, proposed_mk = before_bp, before_mk
    linked = json.loads(args.link_build.read_text())
    assert linked['compiled'] and linked['seccomp_enabled']
    link_libraries = {Path(name).name: Path(name) for name in linked['input_sha256']
                      if name.endswith('.so')}
    readelf = rom / 'prebuilts/clang/host/linux-x86/clang-r596125/bin/llvm-readelf'
    proprietary = set((source / 'proprietary-files.txt').read_text().splitlines())
    entries, checks, dependencies = {}, [], {}
    for item in catalog['libraries']:
        relative = item['path']
        assert re.fullmatch(r'lib64/lib[A-Za-z0-9]+\.so', relative)
        assert 'vendor/' + relative in proprietary
        assert item['module'] == Path(relative).stem
        original = args.firmware.resolve(strict=True) / 'vendor' / relative
        assert sha(original) == item['sha256']
        target = work / 'vendor' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        entries[relative] = dict(source=str(target), original=str(original),
                                 bytes=target.stat().st_size, sha256=sha(target))
        assert entries[relative]['sha256'] == item['sha256']
    for item in catalog['libraries']:
        relative = item['path']
        target = Path(entries[relative]['source'])
        elf = subprocess.check_output([readelf, '-h', '-d', target], text=True)
        assert re.search(r'Machine:\s+AArch64', elf)
        assert 'Library soname: [' + target.name + ']' in elf
        needed = re.findall(r'Shared library: \[(.*?)\]', elf)
        assert needed and all(Path(name).name == name for name in needed)
        command = ['python3', str(rom / 'build/make/tools/check_elf_file.py'),
                   '--llvm-readobj', str(readelf.with_name('llvm-readobj')),
                   '--max-page-size', '4096', '--soname', target.name]
        for name in needed:
            new_entry = entries.get('lib64/' + name)
            if new_entry:
                library = Path(new_entry['source'])
            elif (vendor_tree / 'lib64' / name).is_file():
                library = vendor_tree / 'lib64' / name
            else:
                library = link_libraries[name]
                assert sha(library) == linked['input_sha256'][str(library)]
            dependencies[str(library)] = sha(library)
            command += ['--shared-lib', str(library)]
        command.append(str(target))
        result = subprocess.run(command, capture_output=True, text=True, timeout=55)
        (work / (item['module'] + '-elf.log')).write_text(result.stdout + result.stderr)
        checks.append(dict(library=target.name, command=command, exit_code=result.returncode,
                           output_sha256=item['sha256'], max_page_size=4096))
        result.check_returncode()
        marker = '    name: "' + item['module'] + '",'
        if marker not in proposed_bp:
            proposed_bp += '\n' + module_text(item['module'], relative, needed)
        else:
            assert proposed_bp.count(marker) == 1
            start = proposed_bp.index(marker)
            end = proposed_bp.index('\n}\n', start)
            assert '"proprietary/vendor/' + relative + '"' in proposed_bp[start:end]
            assert all('"' + name.removesuffix('.so') + '"' in proposed_bp[start:end]
                       for name in needed)
        if not re.search(r'^(?:    |PRODUCT_PACKAGES \+= )' + re.escape(item['module'])
                         + r'(?: \\)?$', proposed_mk, re.M):
            proposed_mk += '\nPRODUCT_PACKAGES += ' + item['module'] + '\n'
    proposed_bp = install_cacert_runtime(proposed_bp)
    assert install_cacert_runtime(proposed_bp) == proposed_bp
    proposed_path = work / 'proposed-Android.bp'
    proposed_path.write_text(proposed_bp)
    parsed = subprocess.run([str(rom / 'out/host/linux-x86/bin/bpfmt'), '-l', str(proposed_path)],
                            capture_output=True, text=True, timeout=30)
    (work / 'blueprint-parse.log').write_text(parsed.stdout + parsed.stderr)
    parsed.check_returncode()
    removed = json.loads((source / 'configs/vendor-property-cleanup.json').read_text())
    source_properties = (source / 'properties/vendor.prop').read_text()
    baseline_properties = vendor_tree / 'build.prop'
    lines = baseline_properties.read_text().splitlines(keepends=True)
    for key, value in removed.items():
        assert not re.search(r'^' + re.escape(key) + r'=', source_properties, re.M)
        assert sum(line.rstrip('\r\n') == key + '=' + value for line in lines) == 1
    properties = ''.join(line for line in lines if line.split('=', 1)[0] not in removed)
    property_output = work / 'vendor/build.prop'
    property_output.write_text(properties)
    (work / 'before-Android.bp').write_text(before_bp)
    (work / 'before-sheng-vendor.mk').write_text(before_mk)
    for relative, entry in entries.items():
        target = vendor / 'proprietary/vendor' / relative
        assert not target.exists() or sha(target) == entry['sha256']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(entry['source'], target)
        assert sha(target) == entry['sha256']
    assert bp.read_text() == before_bp and mk.read_text() == before_mk
    bp.write_text(proposed_bp)
    mk.write_text(proposed_mk)
    receipt = dict(kind='vendor-startup', date_utc=datetime.now(timezone.utc).isoformat(), passed=True,
                   entries=entries, checks=checks, dependencies_sha256=dependencies,
                   unchanged_oem_bytes=True, installed=False, ninja_graph_loaded=False,
                   normal_module_build_passed=False, application_apk_unchanged=True,
                   baseline_manifest=str(args.baseline), baseline_sha256=sha(args.baseline),
                   property_update=dict(source=str(property_output), bytes=property_output.stat().st_size,
                                        sha256=sha(property_output), removed=removed,
                                        baseline_sha256=sha(baseline_properties)),
                   source_sha256={name: sha(source / name) for name in (
                       'configs/cacert-runtime.json', 'proprietary-files.txt',
                       'configs/vendor-property-cleanup.json', 'properties/vendor.prop',
                       'tools/postprocess_vendor.py', 'tools/prepare_sheng_cacert_runtime.py')},
                   generated_sha256={str(bp): sha(bp), str(mk): sha(mk)})
    (work / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(dict(passed=True, library_count=len(entries), receipt=str(work / 'receipt.json'))))


if __name__ == '__main__':
    main()
