#!/usr/bin/env python3
"""Compile isolated candidate objects with retained Android/kernel target flags.

No product source/object replacement, image link, packaging, or device access.
"""
import argparse
import contextlib
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]/'tools'))
from build_sheng_fstab_variants import blocks, statements


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch_source(source, relative, patch, root, expected):
    target = root/relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(HERE/patch)],
                   cwd=root, check=True, capture_output=True)
    assert sha(target) == expected
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--kernel', type=Path, required=True,
                        help='retained k618 directory containing out-gki and ws/common')
    parser.add_argument('--clang-bin', type=Path, required=True,
                        help='retained kernel compiler bin directory')
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--keep-work', type=Path,
                        help='new isolated directory; retain objects for explicit candidate linking')
    args = parser.parse_args()
    assert not args.report.exists()
    meta = json.loads((HERE/'candidate-base.json').read_text())
    kernel_source = args.kernel/'ws/common/fs/namespace.c'
    fs_source = args.rom/'system/fs/fs_mgr/fs_mgr_overlayfs_mount.cpp'
    assert sha(kernel_source) == meta['kernel_base_sha256']
    assert sha(fs_source) == meta['fs_mgr_base_sha256']
    kbuild = args.kernel/'out-gki'
    soong = args.rom/'out-clean-ota-20261116/soong'
    module = 'm.libfs_mgr_android_ramdisk_arm64_armv8-2a-dotprod_kryo_static'
    kernel_object = kbuild/'fs/namespace.o'
    fs_object = soong/'.intermediates/system/fs/fs_mgr/libfs_mgr/android_ramdisk_arm64_armv8-2a-dotprod_kryo_static/obj/system/fs/fs_mgr/fs_mgr_overlayfs_mount.o'
    original_hashes = {str(p): sha(p) for p in (kernel_source, fs_source, kernel_object, fs_object)}
    report = dict(scope='isolated object compilation only', objects=[],
                  image_linked=False, product_sources_modified=False,
                  device_access=False, flash=False)
    if args.keep_work:
        args.keep_work.mkdir(parents=True, exist_ok=False)
    work_context = (contextlib.nullcontext(str(args.keep_work)) if args.keep_work else
                    tempfile.TemporaryDirectory(prefix='sheng-magisk-candidate-compile-', dir='/tmp'))
    with work_context as tmp:
        root = Path(tmp)
        k = root/'kernel'; k.mkdir()
        new_kernel = patch_source(kernel_source, 'fs/namespace.c',
                                  'kernel-avoid-unused-source-root-mountpoint.patch',
                                  k, meta['kernel_candidate_sha256'])
        cmd = shlex.split((kbuild/'fs/.namespace.o.cmd').read_text().split(' := ', 1)[1].split('\n', 1)[0])
        assert cmd[0] == 'clang' and cmd[-1] == str(kernel_source)
        assert cmd[1].startswith('-Wp,-MMD,')
        cmd[0] = str(args.clang_bin/'clang')
        cmd[1] = '-Wp,-MMD,' + str(k/'namespace.d')
        cmd[cmd.index('-o') + 1] = str(k/'namespace.o')
        cmd[-1] = str(new_kernel)
        process = subprocess.run(cmd, cwd=kbuild, capture_output=True, text=True, timeout=90)
        report['objects'].append(dict(kind='kernel_namespace', command=cmd,
            source_sha256=sha(new_kernel), returncode=process.returncode,
            stdout=process.stdout, stderr=process.stderr,
            object_sha256=sha(k/'namespace.o') if process.returncode == 0 else None))
        assert process.returncode == 0, process.stderr

        f = root/'fs_mgr'; f.mkdir()
        new_fs = patch_source(fs_source, 'fs_mgr_overlayfs_mount.cpp',
                              'fs_mgr-preserve-file-submounts.patch',
                              f, meta['fs_mgr_candidate_sha256'])
        main_graph = soong/'build.custom_sheng.ninja'
        definitions = [s for s in statements(main_graph) if s.startswith('g.') and ' = ' in s]
        rule = next(b for b in blocks(main_graph) if b[0] == 'rule g.cc.cc')
        flags = next(s for s in statements(soong/'build.custom_sheng.6.ninja')
                     if s.startswith(module + '.cFlags1 = '))
        target = f/'candidate.o'
        graph = '\n'.join(definitions + [flags, 'builddir = ' + str(f),
            '\n'.join(rule), 'build ' + str(target) + ': g.cc.cc ' + str(new_fs),
            '    ccCmd = ${g.android.soong.cc.config.ClangBin}/clang++',
            '    cFlags = ${' + module + '.cFlags1}', '    postCmd = ',
            'default ' + str(target)]) + '\n'
        graph_path = f/'candidate.ninja'; graph_path.write_text(graph)
        cmd = [str(args.rom/'prebuilts/build-tools/linux-x86/bin/ninja'),
               '-f', str(graph_path), '-v', str(target)]
        process = subprocess.run(cmd, cwd=args.rom, capture_output=True, text=True, timeout=90)
        report['objects'].append(dict(kind='android_ramdisk_fs_mgr', command=cmd,
            source_sha256=sha(new_fs), returncode=process.returncode,
            stdout=process.stdout, stderr=process.stderr,
            object_sha256=sha(target) if process.returncode == 0 else None,
            original_compile_rule_and_flags=True))
        assert process.returncode == 0, process.stderr
    assert all(sha(Path(p)) == h for p, h in original_hashes.items())
    report['original_sources_and_product_objects_unchanged'] = True
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(passed=True, isolated_objects=len(report['objects']),
                         original_sources_and_objects_unchanged=True,
                         image_linked=False, flash=False)))


if __name__ == '__main__':
    main()
