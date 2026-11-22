#!/usr/bin/env python3
"""Inspect successful fresh Soong edges, not just source declarations.

This verifies the owned ramdisk link, copied init output dependency, and source
edge coverage. It does not compile, run Make installation, package, or flash.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ARCHIVES = {
    'libsheng_fs_mgr_first_stage.a': 'fs-mgr-first-stage',
    'libsheng_snapshot_init.a': 'snapshot-first-stage',
    'libsheng_crypto_first_stage.a': 'first-stage-crypto',
    'libsheng_unwind_first_stage.a': 'first-stage-unwind',
    'libsheng_zstd_first_stage.a': 'first-stage-zstd',
}
FORBIDDEN = {'libfs_mgr.a', 'libsnapshot_init.a', 'libcrypto_static.a',
             'libunwindstack_no_dex.a', 'libzstd.a'}


def validate_analysis(analysis):
    if not (analysis.get('graph_generation_passed') and analysis.get('inputs_unchanged')
            and analysis.get('source_variants') and analysis.get('module_list_rescanned')
            and analysis.get('returncode') == 0 and analysis.get('guard_stop') is None):
        raise ValueError('A successful terminal fresh source-variant analysis is required')


def validate_source_coverage(actual, lock):
    expected = {folder: set() for folder in actual}
    for row in lock['sources'].values():
        destination = row.get('destination') or ''
        for folder in expected:
            if (destination.startswith('interfaces/compat/' + folder + '/')
                    and destination.endswith('.cpp')):
                expected[folder].add('device/xiaomi/sheng/' + destination)
    if actual != expected or any(not sources for sources in expected.values()):
        raise ValueError('Owned compilation sources differ from the complete pinned source set')


def validate_link(block):
    archives = {}
    for word in '\n'.join(block).split():
        if word.endswith('.a') and not word.startswith('-'):
            archives.setdefault(Path(word).name, set()).add(word)
    if FORBIDDEN.intersection(archives):
        raise ValueError('Original provider reintroduced: ' +
                         ', '.join(sorted(FORBIDDEN.intersection(archives))))
    for name, folder in ARCHIVES.items():
        paths = archives.get(name, set())
        if len(paths) != 1:
            raise ValueError('Missing or ambiguous owned archive: ' + name)
        path = next(iter(paths))
        if ('/device/xiaomi/sheng/interfaces/compat/' + folder + '/') not in path:
            raise ValueError('Archive is not from its owned module: ' + path)
        if '/android_ramdisk_' not in path:
            raise ValueError('Wrong image variant: ' + path)
    return {name: next(iter(archives[name])) for name in ARCHIVES}


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def validate_copy_chain(link, strip, copy):
    link_output = link[0][6:].split(': ', 1)[0]
    if not link_output.endswith('/unstripped/init'):
        raise ValueError('Unexpected init linker output')
    compiled = link_output.replace('/unstripped/init', '/init')
    strip_output, strip_tail = strip[0][6:].split(': ', 1)
    if strip_output != compiled or not strip_tail.split()[0].startswith('g.cc.strip'):
        raise ValueError('Unexpected stripped init producer')
    if link_output not in strip_tail.split()[1:]:
        raise ValueError('Stripped init does not consume this linker output')
    copy_tail = copy[0].split(': ', 1)[1].split()
    if copy_tail[0] not in ('g.android.Cp', 'g.android.CpExecutable'):
        raise ValueError('Root installer is not an executable/file copy edge')
    copy_inputs = copy_tail[1:]
    if compiled not in copy_inputs:
        raise ValueError('Root installer does not copy the freshly stripped init')
    return compiled


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--analysis', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    rom = args.rom.resolve(strict=True)
    analysis = json.loads(args.analysis.read_text())
    validate_analysis(analysis)
    if not analysis.get('input_sha256'):
        raise ValueError('Analysis has no input provenance')
    for path, digest in analysis['input_sha256'].items():
        if sha(Path(path)) != digest:
            raise ValueError('Analysis input changed after completion: ' + path)
    work = Path(analysis['work']).resolve(strict=True)
    if work.parent != rom or not work.name.startswith('out-sheng-remounter-soong-'):
        raise ValueError('Unexpected graph directory')
    report = args.report.resolve()
    if report.exists():
        raise ValueError('Preserve previous graph receipts')
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
    from build_sheng_fstab_variants import blocks
    graphs = sorted((work / 'soong').glob('build.custom_sheng*.ninja'))
    if not graphs:
        raise ValueError('No generated Ninja graph')
    graph_hashes = {str(path): sha(path) for path in graphs}
    links, strips, copies, selected = [], [], [], []
    own_sources = {'first-stage-init': set(), 'fs-mgr-first-stage': set()}
    archive_blocks = {}
    for graph in graphs:
        for block in blocks(graph):
            head = block[0]
            if not head.startswith('build ') or ': ' not in head:
                continue
            outputs, tail = head[6:].split(': ', 1)
            if '/android_ramdisk_' not in outputs:
                continue
            if '/first-stage-init/sheng_init_first_stage/' in outputs and tail.startswith('g.cc.ld '):
                links.append(block)
                selected.append(block)
            if ('/first-stage-init/sheng_init_first_stage/' in outputs
                    and outputs.endswith('/init') and '/unstripped/' not in outputs):
                strips.append(block)
                selected.append(block)
            if (any('/first-stage-init/' + name + '/' in outputs
                    for name in ('init_first_stage', 'prebuilt_init_first_stage'))
                    and outputs.endswith('/init') and '/unstripped/' not in outputs
                    and '/stripped/' not in outputs):
                copies.append(block)
                selected.append(block)
            if tail.startswith('g.cc.cc '):
                source = tail.split()[1]
                for folder in own_sources:
                    prefix = 'device/xiaomi/sheng/interfaces/compat/' + folder + '/'
                    module = 'sheng_init_first_stage' if folder == 'first-stage-init' else 'libsheng_fs_mgr_first_stage'
                    if (source.startswith(prefix) and source.endswith('.cpp')
                            and '/' + folder + '/' + module + '/' in outputs):
                        own_sources[folder].add(source)
            if tail.startswith('g.cc.ar '):
                for name in ARCHIVES:
                    if outputs.endswith('/' + name):
                        if outputs in archive_blocks:
                            raise ValueError('Duplicate archive producer: ' + outputs)
                        archive_blocks[outputs] = block
    if len(links) != 1 or len(strips) != 1 or len(copies) != 1:
        raise ValueError('Expected one owned init linker, strip and root-copy edge')
    providers = validate_link(links[0])
    if any(path not in archive_blocks for path in providers.values()):
        raise ValueError('Missing exact archive producer for init link input')
    archives = {name: archive_blocks[path] for name, path in providers.items()}
    selected.extend(archives.values())
    compiled_init = validate_copy_chain(links[0], strips[0], copies[0])
    if {key: len(value) for key, value in own_sources.items()} != {
            'first-stage-init': 15, 'fs-mgr-first-stage': 9}:
        raise ValueError('Unexpected owned C++ compilation coverage')
    source_lock = Path(__file__).with_name('source-variants-lock.json')
    validate_source_coverage(own_sources, json.loads(source_lock.read_text()))
    unwind = '\n'.join(archives['libsheng_unwind_first_stage.a'])
    if '/external/zstd/libzstd/' in unwind or '/first-stage-zstd/libsheng_zstd_first_stage/' not in unwind:
        raise ValueError('Unwind whole-static zstd ownership is incorrect')
    if any(sha(Path(path)) != digest for path, digest in graph_hashes.items()):
        raise ValueError('Graph changed during inspection')
    gate_command = [sys.executable, str(Path(__file__).with_name('materialize_source_variants.py')),
                    '--rom', str(rom), '--device', str(rom / 'device/xiaomi/sheng'), '--check-only']
    gate = subprocess.run(gate_command, capture_output=True, text=True, check=True)
    if gate.stdout.strip() != 'SHENG_SOURCE_VARIANTS_VERIFIED':
        raise ValueError('Complete pinned-source gate did not succeed')
    receipt = dict(passed=True, scope='fresh owned ramdisk link/source/copy edges only',
                   analysis_sha256=sha(args.analysis), graph_sha256=graph_hashes,
                   archives=providers, compiled_init=compiled_init,
                   owned_cpp_sources={key: sorted(value) for key, value in own_sources.items()},
                   original_private_archives_absent_from_init_link=True,
                   root_copy_uses_compiled_init=True, unwind_uses_owned_zstd=True,
                   complete_source_gate_passed=True, source_gate_command=gate_command,
                   source_lock_sha256=sha(Path(__file__).with_name('source-variants-lock.json')),
                   compiled=False, product_make_install_verified=False,
                   full_product_graph_verified=False, runtime_verified=False, flashed=False)
    report.mkdir(parents=True)
    (report / 'selected-edges.ninja.txt').write_text('\n\n'.join('\n'.join(b) for b in selected) + '\n')
    (report / 'qualification.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({key: value for key, value in receipt.items() if key != 'graph_sha256'}, indent=2))


if __name__ == '__main__':
    main()
