#!/usr/bin/env python3
"""Link retained candidate objects without changing public sources or outputs.

Explicit research build only; does not package, flash, or install anything.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / 'tools'))
from build_sheng_fstab_variants import blocks, statements
from storage_guard import require_build_space

ROM = Path('/root/sheng-pixelos/android')
K = Path('/root/sheng-pixelos/diagnostics/ksu-rawdump-20261117/vendor-kmi32/k618')
O = (K / 'out-gki').resolve()
C = Path('/root/sheng-pixelos/diagnostics/kernel618-android-deps/prebuilts/clang/host/linux-x86/clang-r584948c/bin')


def sha(p):
    digest = hashlib.sha256()
    with p.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    trial = Path(sys.argv[1]).resolve(strict=True)
    require_build_space(trial)
    dest = trial / 'linked'
    dest.mkdir(exist_ok=False)
    receipts = []

    def run(cmd, cwd=dest, env=None):
        n = len(receipts)
        with (dest / f'{n:02d}.stdout').open('wb') as out, (dest / f'{n:02d}.stderr').open('wb') as err:
            p = subprocess.run(list(map(str, cmd)), cwd=cwd, env=env, stdout=out, stderr=err)
        receipts.append(dict(command=list(map(str, cmd)), cwd=str(cwd), returncode=p.returncode))
        (dest / 'commands.json').write_text(json.dumps(receipts, indent=2))
        assert p.returncode == 0, f'command {n} failed; inspect {dest}/{n:02d}.stderr'

    # Android: copy the static library, replace one object, replay exact link edge.
    soong = ROM / 'out-clean-ota-20261116/soong'
    archive = soong / '.intermediates/system/fs/fs_mgr/libfs_mgr/android_ramdisk_arm64_armv8-2a-dotprod_kryo_static/libfs_mgr.a'
    before = {str(p): sha(p) for p in (archive, O / 'fs/namespace.o', O / 'vmlinux', O / 'arch/arm64/boot/Image')}
    newlib = dest / 'libfs_mgr.a'
    shutil.copy2(archive, newlib)
    member = dest / 'fs_mgr_overlayfs_mount.o'
    shutil.copy2(trial / 'objects/fs_mgr/candidate.o', member)
    ar = ROM / 'prebuilts/clang/host/linux-x86/clang-r596125/bin/llvm-ar'
    members = subprocess.check_output([ar, 't', archive], text=True).splitlines()
    assert members.count(member.name) == 1
    run([ar, 'r', newlib, member])
    assert subprocess.check_output([ar, 't', newlib], text=True).splitlines() == members
    main_graph = soong / 'build.custom_sheng.ninja'
    definitions = [s for s in statements(main_graph) if s.startswith('g.') and ' = ' in s]
    rule = next(b for b in blocks(main_graph) if b[0] == 'rule g.cc.ld')
    edge = next(b for b in blocks(soong / 'build.custom_sheng.5.ninja')
                if b[0].startswith('build ') and '/init_first_stage/' in b[0] and ': g.cc.ld ' in b[0])
    original_target = edge[0][6:].split(': ', 1)[0]
    new_target = dest / 'init.unstripped'
    edge = [line.replace(str(archive.relative_to(ROM)), str(newlib)).replace(original_target, str(new_target)) for line in edge]
    graph = dest / 'init-link.ninja'
    graph.write_text('\n'.join(definitions + ['builddir = ' + str(dest), '\n'.join(rule), '\n'.join(edge)]) + '\n')
    run([ROM / 'prebuilts/build-tools/linux-x86/bin/ninja', '-f', graph, '-j1', '-v', new_target], ROM)
    run([ROM / 'prebuilts/clang/host/linux-x86/clang-r596125/bin/llvm-strip', '--strip-debug', '-o', dest / 'init', new_target])

    # Kernel: thin archive points at immutable retained objects, except namespace.
    build = dest / 'kernel'
    build.mkdir()
    for rel in ('include', 'scripts', 'tools', 'arch', 'init'):
        (build / rel).symlink_to(O / rel, target_is_directory=True)
    shutil.copy2(O / '.config', build / '.config')
    shutil.copy2(O / '.vmlinux.export.o', build / '.vmlinux.export.o')
    objects = subprocess.check_output([C / 'llvm-ar', 't', O / 'vmlinux.a'], text=True).splitlines()
    assert objects.count(str(O / 'fs/namespace.o')) == 1
    objects = [str(trial / 'objects/kernel/namespace.o') if p == str(O / 'fs/namespace.o') else p for p in objects]
    rsp = build / 'archive.rsp'
    rsp.write_text('\n'.join(shlex.quote(p) for p in objects))
    run([C / 'llvm-ar', 'cDPrST', 'vmlinux.a', '@' + str(rsp)], build)
    run([C / 'ld.lld', '-EL', '-maarch64elf', '-z', 'norelro', '--fatal-warnings', '--compress-debug-sections=zstd', '-z', 'noexecstack', '-r', '-o', 'vmlinux.o', '--whole-archive', 'vmlinux.a', '--no-whole-archive', '--start-group', O / 'drivers/firmware/efi/libstub/lib.a', '--end-group'], build)
    namespace = trial / 'objects/kernel/namespace.o'
    exports = re.findall(r'\b__export_symbol_(\w+)', subprocess.check_output([C / 'llvm-nm', namespace], text=True))
    crcs = subprocess.run([O / 'scripts/gendwarfksyms/gendwarfksyms', '--stable', namespace],
                          input='\n'.join(exports) + '\n', text=True, capture_output=True, check=True).stdout
    expected = dict(re.findall(r'^#SYMVER (\w+) (0x[0-9a-f]+)', (O / 'fs/.namespace.o.cmd').read_text(), re.M))
    assert dict(re.findall(r'^#SYMVER (\w+) (0x[0-9a-f]+)', crcs, re.M)) == expected
    (namespace.parent / '.namespace.o.cmd').write_text('\n' + crcs)
    original_objects = (O / '.vmlinux.objs').read_text().splitlines()
    (build / '.vmlinux.objs').write_text(''.join(str(namespace if p == 'fs/namespace.o' else O / p) + '\n' for p in original_objects))
    run([O / 'scripts/mod/modpost', '-M', '-m', '-b', '-x', '-E', '-o', 'vmlinux.symvers', 'vmlinux.o'], build)
    old = (O / 'vmlinux.symvers').read_text()
    assert (build / 'vmlinux.symvers').read_text() == old, 'export CRCs changed: modules must be rebuilt'
    pahole = Path('/root/sheng-pixelos/diagnostics/kernel618-android-deps/prebuilts/kernel-build-tools/linux_musl-x86/bin/pahole')
    version = subprocess.check_output([pahole, '--version'], text=True).strip()
    flags = '--btf_gen_floats -j1 --skip_encoding_btf_inconsistent_proto --btf_gen_optimized' if version in ('v1.24', 'v1.25') else '-j1 --btf_features=encode_force,var,float,enum64,decl_tag,type_tag,optimized_func,consistent_func,decl_tag_kfuncs'
    if int(version.split('.')[1]) >= 30:
        flags += ',attributes'
    if 'CONFIG_PAHOLE_HAS_LANG_EXCLUDE=y' in (O / '.config').read_text().splitlines():
        flags += ' --lang_exclude=rust'
    assembly_flags = shlex.join(['-nostdinc', '-D__ASSEMBLY__', '-D__KERNEL__',
        '-I' + str(K / 'ws/common/arch/arm64/include'), '-I./arch/arm64/include/generated',
        '-I' + str(K / 'ws/common/include'), '-I./include',
        '-I' + str(K / 'ws/common/arch/arm64/include/uapi'), '-I./arch/arm64/include/generated/uapi',
        '-I' + str(K / 'ws/common/include/uapi'), '-I./include/generated/uapi',
        '-include', str(K / 'ws/common/include/linux/kconfig.h')])
    env = dict(os.environ, PATH=str(C) + ':' + os.environ['PATH'],
               srctree=str(K / 'ws/common'), objtree=str(build), SRCARCH='arm64',
               MAKE='true', CC='clang --target=aarch64-linux-gnu', NM='llvm-nm',
               OBJCOPY='llvm-objcopy', CONFIG_SHELL='/bin/sh',
               KBUILD_LDS='arch/arm64/kernel/vmlinux.lds',
               KBUILD_VMLINUX_LIBS=str(O / 'drivers/firmware/efi/libstub/lib.a'),
               PAHOLE=str(pahole), PAHOLE_FLAGS=flags,
               RESOLVE_BTFIDS=str(O / 'tools/bpf/resolve_btfids/resolve_btfids'),
               RESOLVE_BTFIDS_FLAGS='--fatal_warnings', KBUILD_CFLAGS='--target=aarch64-linux-gnu',
               KBUILD_AFLAGS=assembly_flags)
    cmd = shlex.split((O / '.vmlinux.unstripped.cmd').read_text().split(' := ', 1)[1].split(';', 1)[0])
    run(cmd, build, env)
    run([C / 'llvm-objcopy', '--set-section-flags', '.modinfo=noload', 'vmlinux.unstripped', 'vmlinux'], build)
    run([C / 'llvm-objcopy', '--remove-section=.modinfo', '-w', '--strip-unneeded-symbol=__mod_device_table__*', 'vmlinux'], build)
    run([C / 'llvm-objcopy', '-O', 'binary', '-R', '.note', '-R', '.note.gnu.build-id', '-R', '.comment', '-S', 'vmlinux', 'Image'], build)
    assert all(sha(Path(p)) == h for p, h in before.items())
    (dest / 'qualification.json').write_text(json.dumps(dict(passed=True, originals_unchanged=True,
        image_sha256=sha(build / 'Image'), init_sha256=sha(dest / 'init'), export_crcs_identical=True,
        module_btf_qualification_pending=True, packaged=False, flashed=False), indent=2))
    print('Isolated links completed:', dest)


if __name__ == '__main__':
    main()
