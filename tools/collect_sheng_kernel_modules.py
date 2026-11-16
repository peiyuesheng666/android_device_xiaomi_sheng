#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Collect one completed kernel's modules, including its core modules.order.

This stages unchanged binaries for depmod and ABI review. It does not select
autoload roots, sign, alter modules, switch BoardConfig or authorize flashing.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil


def digest(path):
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def checked_path(root, value):
    relative = PurePosixPath(value)
    if relative.is_absolute() or '..' in relative.parts or not re.fullmatch(r'[A-Za-z0-9_./+-]+', value):
        raise ValueError(f'Invalid kernel input path: {value}')
    path = (root/value).resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f'Kernel input leaves source root: {value}')
    return path


def name(value):
    return Path(value).name.removesuffix('.ko').replace('-', '_')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--core-build', type=Path, required=True)
    parser.add_argument('--reference-map', type=Path, required=True)
    parser.add_argument('--policy', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root, core = args.source_root.resolve(strict=True), args.core_build.resolve(strict=True)
    if args.output.exists():
        raise ValueError('Output must be a new directory; inspect old stages instead of overwriting them')
    ready = json.loads((core/'.modules-ready.json').read_text())
    expected_hashes = {}
    for row in (core/'module-build-hashes.tsv').read_text().splitlines():
        module, value = row.split('\t')
        if module in expected_hashes:
            raise ValueError(f'Duplicate recorded module: {module}')
        expected_hashes[module] = value
    if digest(core/'module-build-hashes.tsv') != ready['module_hashes_sha256']:
        raise ValueError('Reference module hashes no longer match the completed build')
    if digest(args.reference_map) != ready['module_map_sha256']:
        raise ValueError('Reference module map changed after compilation')
    mapping = json.loads(args.reference_map.read_text())
    if len(mapping) != ready['module_count'] or set(mapping) != set(expected_hashes):
        raise ValueError('Reference inventory differs from its build receipt')
    policy = json.loads(args.policy.read_text())
    overrides = policy['reference_overrides']
    if any(not isinstance(reason, str) or not reason.strip() for reason in overrides.values()):
        raise ValueError('Every provider override needs an explicit reason')
    selected, replaced = {}, {}
    for filename, value in mapping.items():
        if PurePosixPath(filename).name != filename or not filename.endswith('.ko'):
            raise ValueError(f'Invalid output module filename: {filename}')
        source = checked_path(core, value[4:]) if value.startswith('out/') else checked_path(root, value)
        checksum = digest(source)
        if checksum != expected_hashes[filename]:
            raise ValueError(f'Module changed after compilation: {filename}')
        key = name(filename)
        if key in selected:
            raise ValueError(f'Ambiguous reference module name: {key}')
        selected[key] = dict(filename=filename, path=str(source), sha256=checksum, origin='reference')
    for value in (core/'modules.order').read_text().splitlines():
        relative = str(PurePosixPath(value).with_suffix('.ko'))
        source = checked_path(core, relative)
        key = name(source.name)
        if key in selected:
            if Path(selected[key]['path']) == source:
                continue
            if key not in overrides or key in replaced:
                raise ValueError(f'Unreviewed duplicate core/SoC provider: {key}')
            replaced[key] = dict(core_path=str(source), core_sha256=digest(source),
                                 selected_path=selected[key]['path'], reason=overrides[key])
        else:
            selected[key] = dict(filename=source.name, path=str(source), sha256=digest(source), origin='core')
    if set(replaced) != set(overrides):
        raise ValueError('Provider policy contains stale overrides that do not match this build')
    additional_orders = {}
    for key, entry in policy.get('additional_modules', {}).items():
        source = checked_path(root, entry['source'])
        order = checked_path(root, entry['order'])
        if key != name(source.name) or key in selected or not source.name.endswith('.ko'):
            raise ValueError(f'Ambiguous additional module: {key}')
        if not isinstance(entry['reason'], str) or not entry['reason'].strip():
            raise ValueError(f'Additional module needs a reason: {key}')
        ordered = {order.parent/PurePosixPath(row).with_suffix('.ko')
                   for row in order.read_text().splitlines() if row.strip()}
        if source not in ordered:
            raise ValueError(f'Additional module was not in the completed build order: {key}')
        selected[key] = dict(filename=source.name, path=str(source), sha256=digest(source),
                             origin='android_addition', reason=entry['reason'])
        additional_orders[str(order)] = digest(order)
    builtin = {name(value) for value in (core/'modules.builtin').read_text().splitlines()}
    if builtin & selected.keys():
        raise ValueError('Selected modules conflict with builtins: ' + ', '.join(sorted(builtin & selected.keys())))
    release = (core/'include/config/kernel.release').read_text().strip()
    if not re.fullmatch(r'[A-Za-z0-9_.+-]+', release):
        raise ValueError('Invalid kernel release directory')
    target = args.output/'lib/modules'/release
    (target/'kernel').mkdir(parents=True)
    for row in selected.values():
        destination = target/'kernel'/row['filename']
        shutil.copyfile(row['path'], destination)
        if digest(destination) != row['sha256']:
            raise ValueError(f'Module copy mismatch: {destination}')
    for filename in ('modules.builtin', 'modules.builtin.modinfo'):
        shutil.copyfile(core/filename, target/filename)
    (target/'modules.order').write_text(''.join('kernel/' + selected[key]['filename']+'\n' for key in sorted(selected)))
    report = dict(schema=1, kernel_release=release, unchanged_module_bytes=True,
        metadata_directory=str(target.resolve()), modules=selected,
        reference_provider_overrides=replaced, abi_verified=False, bootable_verified=False,
        additional_module_orders_sha256=additional_orders,
        inputs_sha256={str(path): digest(path) for path in (args.reference_map, args.policy,
            core/'module-build-hashes.tsv', core/'.modules-ready.json', core/'kernel-Image',
            core/'kernel.config', core/'Module.symvers', core/'modules.order', core/'modules.builtin')})
    (args.output/'collection.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f'Collected {len(selected)} modules from this build; depmod, ABI and hardware checks remain required.')


if __name__ == '__main__':
    main()
