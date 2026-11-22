#!/usr/bin/env python3
"""Build the three fstab prebuilt variants from exact existing Ninja edges.

Avoid loading a multi-gigabyte ROM graph just for six copy edges. No image rebuild
or device operations. Reject unexpected dependencies/commands instead of guessing.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

from test_sheng_magisk_overlay_handoff import check_fstab

SOURCE = 'device/xiaomi/sheng/rootdir/etc/fstab.qcom'
COPY_COMMAND = ('prebuilts/build-tools/path/linux-x86/rm -f ${out} && '
                'prebuilts/build-tools/path/linux-x86/cp ${g.android.cpPreserveSymlinks} '
                '${cpFlags} ${in} ${out}${extraCmds}')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def statements(path):
    """Read Ninja continuation lines without loading the full graph into memory."""
    with path.open() as stream:
        pending = []
        for line in stream:
            text = line.rstrip('\n')
            if pending:
                text = text.lstrip()
            trailing_dollars = len(text) - len(text.rstrip('$'))
            if trailing_dollars % 2:
                pending.append(text[:-1])
                continue
            pending.append(text)
            yield ''.join(pending)
            pending = []
        assert not pending, 'Unterminated Ninja continuation'


def blocks(path):
    block = []
    for line in statements(path):
        if line and not line.startswith((' ', '\t')):
            if block:
                yield block
            block = [line]
        elif block:
            block.append(line)
    if block:
        yield block


def build_edge(block):
    head = block[0]
    assert head.startswith('build ') and ': ' in head
    target, tail = head[6:].split(': ', 1)
    words = tail.split()
    assert len(target.split()) == 1 and words
    return target, words[0], words[1:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--out-dir', default='out-clean-ota-20261116')
    parser.add_argument('--receipt-dir', type=Path, required=True)
    args = parser.parse_args()
    rom, receipt = args.rom.resolve(strict=True), args.receipt_dir.resolve()
    assert not receipt.exists(), 'Preserve previous results'
    relative_out = Path(args.out_dir)
    assert not relative_out.is_absolute() and '..' not in relative_out.parts
    out = rom/relative_out
    workspace = Path(__file__).resolve().parents[4]
    source = rom/SOURCE
    assert source.read_bytes() == (workspace/SOURCE).read_bytes(), 'Source mirror differs'
    check_fstab(source)
    product = relative_out.as_posix() + '/target/product/sheng/'
    targets = {product + suffix for suffix in ('vendor/etc/fstab.qcom',
               'vendor_ramdisk/system/etc/fstab.qcom', 'recovery/root/system/etc/recovery.fstab')}
    selected, rules, dep_edges = {}, {}, {}
    make_graph = out/'build-custom_sheng.ninja'
    # First discover the three real install edges, then only their exact intermediates.
    for block in blocks(make_graph):
        if block[0].startswith('rule '):
            if any('description = Install: ' + target in line for target in targets for line in block):
                rules[block[0][5:]] = block
        elif block[0].startswith('build ') and any(block[0].startswith('build ' + t + ': ') for t in targets):
            target, rule, deps = build_edge(block)
            assert len(deps) == 1 and rule in rules
            expected = f'/bin/bash -c "rm -f {target} && cp -f -d {deps[0]} {target}"'
            commands = [line.strip()[10:] for line in rules[rule] if line.strip().startswith('command = ')]
            assert commands == [expected], ('Unexpected install command', target)
            selected[target] = block
    assert set(selected) == targets
    intermediates = {build_edge(b)[2][0] for b in selected.values()}
    assert len(intermediates) == 3
    soong_main = out/'soong/build.custom_sheng.ninja'
    cp_rule = None
    for block in blocks(soong_main):
        if block[0] == 'g.android.cpPreserveSymlinks = -d':
            dep_edges['cp_variable'] = block
        elif block[0] == 'rule g.android.CpRule':
            cp_rule = block
        elif block[0].startswith(('build Rm-deps: ', 'build Cp-deps: ')):
            target, rule, deps = build_edge(block)
            assert rule == 'phony' and len(deps) == 2
            assert all(d.startswith('prebuilts/build-tools/') and (rom/d).exists() for d in deps)
            dep_edges[target] = block
    assert cp_rule and set(dep_edges) == {'cp_variable', 'Rm-deps', 'Cp-deps'}
    assert [line.strip()[10:] for line in cp_rule if line.strip().startswith('command = ')] == [COPY_COMMAND]
    shards = sorted((out/'soong').glob('build.custom_sheng.[0-9].ninja'))
    matched = subprocess.check_output([
        'rg', '-l', '-m', '1', '^# Module:  (fstab[.]sheng|custom_sheng_generated_recovery_fstab)$',
        *map(str, shards)], text=True).splitlines()
    for graph in map(Path, matched):
        for block in blocks(graph):
            if not block[0].startswith('build '):
                continue
            if not any(block[0].startswith('build ' + name + ': ') for name in intermediates):
                continue
            target, rule, deps = build_edge(block)
            assert rule == 'g.android.CpRule' and deps == [SOURCE, '|', 'Rm-deps', 'Cp-deps']
            assert all(not re.match(r'\s*(cpFlags|extraCmds)\s*=', line) for line in block[1:])
            assert target not in selected
            selected[target] = block
        if intermediates <= set(selected):
            break
    assert set(selected) == targets | intermediates
    for name in selected:
        path = rom/name
        assert path.resolve().is_relative_to(out.resolve()) and not path.is_symlink()
        assert not path.exists() or path.is_file(), 'Unexpected non-file output'
        if name in targets:
            assert path.is_file(), 'Expected an existing installed fstab'
    receipt.mkdir(parents=True)
    before = {}
    for index, name in enumerate(sorted(selected)):
        path = rom/name
        backup = receipt/f'before-{index}.fstab'
        if path.exists():
            backup.write_bytes(path.read_bytes())
            before[name] = dict(sha256=sha(path), backup=str(backup))
        else:
            before[name] = dict(sha256=None, backup=None, existed=False)
    scratch = Path(tempfile.mkdtemp(prefix='sheng-fstab-ninja-'))
    content = f'builddir = {scratch}\n\n'
    for block in [*dep_edges.values(), cp_rule, *rules.values(), *selected.values()]:
        content += '\n'.join(block) + '\n\n'
    ninja_file = receipt/'fstab-extracted.ninja'
    ninja_file.write_text(content)
    ninja = rom/'prebuilts/build-tools/linux-x86/bin/ninja'
    command = [str(ninja), '-f', str(ninja_file), '-j1', '-v', *sorted(targets)]
    process = subprocess.run(command, cwd=rom, capture_output=True, text=True, timeout=90)
    (receipt/'ninja.stdout').write_text(process.stdout)
    (receipt/'ninja.stderr').write_text(process.stderr)
    assert process.returncode == 0, process.stderr
    after = {name: sha(rom/name) for name in sorted(selected)}
    assert set(after.values()) == {sha(source)}, 'Fstab outputs diverged from source'
    result = dict(passed=True, build_scope='six original Ninja copy edges only',
                  source_sha256=sha(source), before=before, after=after,
                  extracted_ninja_sha256=sha(ninja_file), command=command,
                  full_rom_build=False, images_rebuilt=False, device_access=False,
                  flash=False, reboot=False)
    (receipt/'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
