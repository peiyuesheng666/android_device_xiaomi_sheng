#!/usr/bin/env python3
"""Compile all copied init/fs_mgr C++ files and link an isolated first-stage.

Replays retained exact product edges, rebasing only owned source/include/output
paths and the fs_mgr archive. This is NOT a regenerated Soong/product build.
Snapshot provider sources are also recompiled against the owned headers.
Unchanged whole-static providers and other libraries remain retained inputs.
In particular this replay retains the original crypto/unwind/zstd providers;
it does NOT qualify compilation of their newer source-owned module variants.
No public source, original output, package image or tablet is modified.
"""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'tools'))
from build_sheng_fstab_variants import blocks, statements
from materialize_source_variants import safe_relative
from storage_guard import require_build_space


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rebase_local_includes(line, paths):
    # Only local module headers move. Sibling dependency exports such as
    # fs_mgr/libfstab/include and fs_mgr/libfs_avb/include stay upstream.
    for old, new in paths.items():
        pattern = r'(?<!\S)-I' + re.escape(old) + r'(/include)?(?=\s|$)'
        line = re.sub(pattern, lambda match: '-I' + new + (match[1] or ''), line)
    return line


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    rom, out = args.rom.resolve(strict=True), args.out.resolve()
    assert not out.exists()
    require_build_space(out, minimum_output=64 * 1024**2, minimum_host=6 * 1024**3)
    soong = rom / 'out-clean-ota-20261116/soong'
    archive = soong / '.intermediates/system/fs/fs_mgr/libfs_mgr/android_ramdisk_arm64_armv8-2a-dotprod_kryo_static/libfs_mgr.a'
    snapshot_archive = soong / '.intermediates/system/fs/fs_mgr/libsnapshot/libsnapshot_init/android_ramdisk_arm64_armv8-2a-dotprod_kryo_static/libsnapshot_init.a'
    lock = json.loads((HERE / 'source-variants-lock.json').read_text())
    owned = rom / 'device/xiaomi/sheng'
    originals = {path: sha(path) for path in (archive, snapshot_archive)}
    sources = {}
    for relative, row in lock['sources'].items():
        path = rom / safe_relative(relative)
        assert sha(path) == row['sha256']
        originals[path] = row['sha256']
        if row.get('destination'):
            copied = owned / safe_relative(row['destination'])
            assert sha(copied) == row['output_sha256']
            originals[copied] = row['output_sha256']
            if copied.suffix == '.cpp' and row['destination'].startswith((
                    'interfaces/compat/first-stage-init/', 'interfaces/compat/fs-mgr-first-stage/')):
                sources[relative] = copied
    assert len(sources) == 24
    with (rom / 'out-clean-ota-20261116/.sheng-device-modules.lock').open('a') as build_lock:
        fcntl.flock(build_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        out.mkdir(parents=True)
        definitions = [s for s in statements(soong / 'build.custom_sheng.ninja')
                       if s.startswith('g.') and ' = ' in s]
        rules = [b for b in blocks(soong / 'build.custom_sheng.ninja')
                 if b[0] in ('rule g.cc.cc', 'rule g.cc.ld')]
        assert len(rules) == 2
        modules = ('m.libfs_mgr_android_ramdisk_arm64_armv8-2a-dotprod_kryo_static.',
                   'm.init_first_stage_android_ramdisk_arm64_armv8-2a-dotprod_kryo.',
                   'm.libsnapshot_init_android_ramdisk_arm64_armv8-2a-dotprod_kryo_static.')
        local_paths = {
            'system/fs/fs_mgr': 'device/xiaomi/sheng/interfaces/compat/fs-mgr-first-stage',
            'system/core/init': 'device/xiaomi/sheng/interfaces/compat/first-stage-init',
            'system/fs/fs_mgr/libsnapshot': 'device/xiaomi/sheng/interfaces/compat/snapshot-first-stage',
        }

        def includes(line):
            result = rebase_local_includes(line, local_paths)
            if line.startswith(modules[0]) and ' = ' in line:
                # Match the source-owned Blueprint's private sibling include.
                local = '-I' + local_paths['system/fs/fs_mgr']
                result = result.replace(local + ' ', local + ' -Isystem/fs/fs_mgr ', 1)
            return result

        edges, object_map, found = [], {}, set()
        linker = None
        snapshot_sources = set()
        for shard in ('build.custom_sheng.5.ninja', 'build.custom_sheng.6.ninja', 'build.custom_sheng.7.ninja'):
            for line in statements(soong / shard):
                if line.startswith(modules) and ' = ' in line:
                    definitions.append(includes(line))
            for block in blocks(soong / shard):
                head = block[0]
                if not head.startswith('build '):
                    continue
                if '/init_first_stage/' in head and ': g.cc.ld ' in head:
                    assert linker is None
                    linker = block
                if ': g.cc.cc ' not in head:
                    continue
                target, rest = head[6:].split(': g.cc.cc ', 1)
                source = rest.split()[0]
                is_snapshot = '/libsnapshot_init/android_ramdisk_' in target
                if is_snapshot:
                    assert source not in sources
                    # Snapshot implementation and generated protobuf are unchanged;
                    # rebuild them with the source-owned header/dependency variant.
                    if source.endswith('.cpp'):
                        assert source in lock['sources'], 'Unpinned snapshot implementation: ' + source
                    else:
                        assert source.endswith('/gen/proto/android/snapshot/snapshot.pb.cc')
                    sources[source] = rom / source
                    originals[rom / source] = sha(rom / source)
                    snapshot_sources.add(source)
                if source not in sources:
                    continue
                if ('/libfs_mgr/android_ramdisk_' not in target and
                        '/init_first_stage/android_ramdisk_' not in target and not is_snapshot):
                    continue
                assert source not in found
                found.add(source)
                group = ('snapshot_objects' if is_snapshot else
                         'fs_mgr' if source.startswith('system/fs/fs_mgr/') else 'init_objects')
                output = out / group / Path(target).name
                output.parent.mkdir(exist_ok=True)
                object_map[target] = str(output)
                originals[rom / target] = sha(rom / target)
                rewritten = [line.replace(target, str(output)).replace(' ' + source, ' ' + str(sources[source]))
                             for line in block]
                edges.append(rewritten)
        assert found == set(sources), 'Missing or duplicate retained compilation edge'
        assert len(snapshot_sources) == 10, 'Unexpected snapshot source filegroup'
        assert linker is not None
        # Preserve the real generated-header prerequisites. Never replace dedup
        # prerequisites with empty phony nodes to make an isolated replay pass.
        pending = set(re.findall(r'\bdedup-[0-9a-f]+\b', '\n'.join(
            line for block in edges + [linker] for line in block)))
        phony = {}
        while pending - phony.keys():
            required = pending - phony.keys()
            graphs = [soong / 'build.custom_sheng.ninja', *sorted(soong.glob('build.custom_sheng.*.ninja'))]
            for original_graph in graphs:
                if not pending - phony.keys():
                    break
                for block in blocks(original_graph):
                    head = block[0]
                    if not head.startswith('build '):
                        continue
                    name, tail = head[6:].split(': ', 1)
                    if name not in pending or name in phony:
                        continue
                    assert tail == 'phony' or tail.startswith('phony '), 'Missing prerequisite needs a real rebuild: ' + name
                    phony[name] = block
                    for path in tail.split()[1:]:
                        if path in ('|', '||'):
                            continue
                        if (rom / path).is_file():
                            originals[rom / path] = sha(rom / path)
                        else:
                            pending.add(path)
            assert required <= phony.keys(), 'Missing retained prerequisite definition'
        prerequisites = list(phony.values())
        graph = out / 'compile.ninja'
        graph.write_text('\n'.join(definitions + ['builddir = ' + str(out)] +
                                   ['\n'.join(b) for b in rules + prerequisites + edges]) + '\n')
        ninja = rom / 'prebuilts/build-tools/linux-x86/bin/ninja'
        commands = []

        def run(command):
            index = len(commands)
            commands.append(list(map(str, command)))
            (out / 'commands.json').write_text(json.dumps(commands, indent=2))
            p = subprocess.run(command, cwd=rom, capture_output=True)
            (out / f'{index:02d}.stdout').write_bytes(p.stdout)
            (out / f'{index:02d}.stderr').write_bytes(p.stderr)
            assert p.returncode == 0, f'Command {index} failed; preserve {out}'

        run([ninja, '-f', graph, '-j1', '-v', *object_map.values()])
        library = out / 'libsheng_fs_mgr_first_stage.a'
        shutil.copy2(archive, library)
        ar = rom / 'prebuilts/clang/host/linux-x86/clang-r596125/bin/llvm-ar'
        members = subprocess.check_output([ar, 't', archive], text=True).splitlines()
        replacements = sorted((out / 'fs_mgr').glob('*.o'))
        assert len(replacements) == 9 and all(members.count(p.name) == 1 for p in replacements)
        run([ar, 'r', library, *replacements])
        assert subprocess.check_output([ar, 't', library], text=True).splitlines() == members
        snapshot_library = out / 'libsheng_snapshot_init.a'
        shutil.copy2(snapshot_archive, snapshot_library)
        snapshot_members = subprocess.check_output([ar, 't', snapshot_archive], text=True).splitlines()
        snapshot_replacements = sorted((out / 'snapshot_objects').glob('*.o'))
        assert len(snapshot_replacements) == 10
        assert all(snapshot_members.count(p.name) == 1 for p in snapshot_replacements)
        run([ar, 'r', snapshot_library, *snapshot_replacements])
        assert subprocess.check_output([ar, 't', snapshot_library], text=True).splitlines() == snapshot_members
        old_target = linker[0][6:].split(': ', 1)[0]
        originals[rom / old_target] = sha(rom / old_target)
        unstripped = out / 'init.unstripped'
        rewritten = []
        for line in linker:
            line = line.replace(old_target, str(unstripped))
            line = line.replace(str(archive.relative_to(rom)), str(library))
            line = line.replace(str(snapshot_archive.relative_to(rom)), str(snapshot_library))
            for old, new in object_map.items():
                line = line.replace(old, new)
            rewritten.append(line)
        assert str(archive.relative_to(rom)) not in '\n'.join(rewritten)
        assert str(snapshot_archive.relative_to(rom)) not in '\n'.join(rewritten)
        link_graph = out / 'link.ninja'
        link_graph.write_text('\n'.join(definitions + ['builddir = ' + str(out)] +
                                       ['\n'.join(b) for b in rules + prerequisites + [rewritten]]) + '\n')
        run([ninja, '-f', link_graph, '-j1', '-v', unstripped])
        binary = out / 'init'
        run([rom / 'prebuilts/clang/host/linux-x86/clang-r596125/bin/llvm-strip',
             '--strip-debug', '-o', binary, unstripped])
        assert all(sha(path) == expected for path, expected in originals.items())
        receipt = dict(passed=True, scope='isolated retained-edge source-variant compile/link',
                       cpp_files_compiled=len(sources), fs_mgr_members_replaced=len(replacements),
                       snapshot_objects_compiled=len(snapshot_replacements),
                       snapshot_archive_sha256=sha(snapshot_library),
                       snapshot_generated_proto_reused=True,
                       unchanged_whole_static_provider_objects_retained=True,
                       source_owned_crypto_unwind_zstd_compiled=False,
                       archive_membership_unchanged=True, pinned_inputs_and_original_outputs_unchanged=True,
                       generated_header_prerequisites_preserved=True,
                       archive_sha256=sha(library), init_sha256=sha(binary),
                       public_sources_modified=False, regenerated_soong_graph=False,
                       product_install_verified=False, full_source_product_build=False,
                       device_access=False, flashed=False, input_sha256={str(p): s for p, s in originals.items()})
        (out / 'qualification.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps({k: v for k, v in receipt.items() if k != 'input_sha256'}, indent=2), flush=True)


if __name__ == '__main__':
    main()
