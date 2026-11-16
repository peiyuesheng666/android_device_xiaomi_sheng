#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Plan Android module partitions from one kernel's actual depmod metadata.

This computes dependency closure only. It does not verify module ABI, signatures,
BTF, device-tree coverage or bootability, and must not authorize flashing.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


def module_name(value):
    return PurePosixPath(value).name.removesuffix('.ko').replace('-', '_')


def module_path(value):
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or not value.endswith('.ko'):
        raise ValueError(f'Invalid module path: {value}')
    if not re.fullmatch(r'[A-Za-z0-9_./+-]+', value):
        raise ValueError(f'Unsupported module path: {value}')
    return value


class ModuleGraph:
    def __init__(self, dependencies, builtin, softdeps='', optional_softdeps=(), kernel_config=''):
        self.paths, self.hard, self.pre, self.post = {}, {}, {}, {}
        self.builtin = set()
        for line in builtin.splitlines():
            if line.strip():
                self.builtin.add(module_name(module_path(line.strip())))
        rows = []
        for line in dependencies.splitlines():
            if not line.strip():
                continue
            path, separator, rest = line.partition(':')
            if not separator:
                raise ValueError(f'Malformed modules.dep row: {line}')
            path = module_path(path.strip())
            name = module_name(path)
            if name in self.paths or name in self.builtin:
                raise ValueError(f'Ambiguous loadable/builtin module: {name}')
            self.paths[name] = path
            rows.append((name, [module_path(item) for item in rest.split()]))
        if not self.paths:
            raise ValueError('No loadable modules in modules.dep')
        for name, paths in rows:
            self.hard[name] = set()
            for path in paths:
                target = module_name(path)
                if self.paths.get(target) != path:
                    raise ValueError(f'Unresolved dependency path for {name}: {path}')
                self.hard[name].add(target)
        known = set(self.paths) | self.builtin
        optional = {}
        for rule in optional_softdeps:
            owner, target = module_name(rule['owner']), module_name(rule['dependency'])
            option, reason = rule['config'], rule['reason']
            if not re.fullmatch(r'CONFIG_[A-Z0-9_]+', option) or not reason.strip():
                raise ValueError('Optional softdep needs a configuration symbol and reason')
            if f'# {option} is not set' not in kernel_config.splitlines() or re.search(
                    r'^' + option + r'=', kernel_config, re.MULTILINE):
                raise ValueError(f'Optional softdep configuration is not explicitly disabled: {option}')
            if owner not in known or target in known or (owner, target) in optional:
                raise ValueError(f'Stale or ambiguous optional softdep rule: {owner}/{target}')
            optional[owner, target] = dict(owner=owner, dependency=target, config=option, reason=reason)
        self.optional_softdeps = []
        used_optional = set()
        for line in softdeps.splitlines():
            fields = line.split('#', 1)[0].split()
            if not fields:
                continue
            if len(fields) < 3 or fields[0] != 'softdep':
                raise ValueError(f'Malformed modules.softdep row: {line}')
            name = module_name(fields[1])
            if name not in known:
                raise ValueError(f'Unknown softdep owner: {name}')
            destination = None
            for field in fields[2:]:
                if field in ('pre:', 'post:'):
                    table = self.pre if field == 'pre:' else self.post
                    destination = table.setdefault(name, set())
                else:
                    target = module_name(field)
                    if destination is None:
                        raise ValueError(f'Unresolved softdep for {name}: {field}')
                    if target in known:
                        destination.add(target)
                    elif (name, target) in optional:
                        used_optional.add((name, target))
                    else:
                        raise ValueError(f'Unresolved softdep for {name}: {field}')
        if used_optional != set(optional):
            raise ValueError('Optional softdep rules do not match this depmod inventory')
        self.optional_softdeps = [optional[key] for key in sorted(used_optional)]

    def closure(self, roots):
        pending = [module_name(item) for item in roots]
        seen = set()
        while pending:
            name = pending.pop()
            if name in seen:
                continue
            if name not in self.paths and name not in self.builtin:
                raise ValueError(f'Required module is missing: {name}')
            seen.add(name)
            pending.extend(self.hard.get(name, set()) | self.pre.get(name, set()) |
                           self.post.get(name, set()))
        return seen - self.builtin

    def ordered(self, selected):
        before = {name: (self.hard.get(name, set()) | self.pre.get(name, set())) & selected
                  for name in selected}
        for name in selected:
            for after in self.post.get(name, set()) & selected:
                before[after].add(name)
        result = []
        while before:
            ready = sorted(name for name, dependencies in before.items() if not dependencies)
            if not ready:
                raise ValueError('Cyclic module load order: ' + ', '.join(sorted(before)))
            result.extend(ready)
            for name in ready:
                del before[name]
            for dependencies in before.values():
                dependencies.difference_update(ready)
        return [self.paths[name] for name in result]

    def plan(self, roots, exclusions):
        groups = {'first_stage', 'recovery', 'system_dlkm', 'vendor_dlkm'}
        if set(roots) != groups or any(not isinstance(v, list) for v in roots.values()):
            raise ValueError('Explicit first_stage/recovery/system_dlkm/vendor_dlkm roots required')
        if any(not isinstance(reason, str) or not reason.strip() for reason in exclusions.values()):
            raise ValueError('Every excluded module needs a reason')
        excluded = {module_name(name) for name in exclusions}
        if not excluded <= set(self.paths):
            raise ValueError('An excluded module is not in this kernel inventory')
        closures = {group: self.closure(names) for group, names in roots.items()}
        required = set().union(*closures.values())
        if required & excluded:
            raise ValueError('Excluded module is required: ' + ', '.join(sorted(required & excluded)))
        retained = set(self.paths) - excluded
        # Even installed-but-not-autoloaded modules must retain their dependencies.
        for name in retained:
            if self.closure([name]) & excluded:
                raise ValueError(f'Retained module depends on an exclusion: {name}')
        boot = closures['first_stage'] | closures['recovery']
        # Android's normal depmod inventory must include first-stage providers
        # as well. The vendor ramdisk disappears after switching root, and the
        # normal module build resolves dependencies only against DLKM copies.
        # Match the ROM's source-kernel packaging: retain every module in DLKM
        # and additionally copy the boot/recovery closure into vendor_boot.
        system = closures['system_dlkm']
        vendor = retained - system
        # Validate ordering globally as well as within each load group.
        self.ordered(retained)
        return {
            'install': {'vendor_boot': self.ordered(boot),
                        'system_dlkm': self.ordered(system),
                        'vendor_dlkm': self.ordered(vendor)},
            'load': {'first_stage': self.ordered(closures['first_stage']),
                     'recovery': self.ordered(closures['recovery']),
                     'system_dlkm': self.ordered(system),
                     'vendor_dlkm': self.ordered(closures['vendor_dlkm'] & vendor)},
            'builtin_roots': {group: sorted({module_name(n) for n in names} & self.builtin)
                              for group, names in roots.items()},
            'exclusions': exclusions,
            'configured_optional_softdeps': self.optional_softdeps,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', type=Path, required=True,
                        help='Same-kernel depmod directory with modules.dep/builtin/softdep')
    parser.add_argument('--requirements', type=Path, required=True,
                        help='JSON containing explicit roots and exclusions')
    parser.add_argument('--kernel-config', type=Path,
                        help='Actual .config, required for explicitly disabled optional softdeps')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    inputs = {name: (args.metadata / name).read_bytes()
              for name in ('modules.dep', 'modules.builtin', 'modules.softdep')}
    requirements = json.loads(args.requirements.read_text())
    if args.kernel_config:
        inputs['kernel.config'] = args.kernel_config.read_bytes()
    graph = ModuleGraph(*(inputs[name].decode() for name in
                          ('modules.dep', 'modules.builtin', 'modules.softdep')),
                        optional_softdeps=requirements.get('optional_softdeps', []),
                        kernel_config=inputs.get('kernel.config', b'').decode())
    plan = graph.plan(requirements['roots'], requirements.get('exclusions', {}))
    plan.update(schema=1, dependency_closure_verified=True, bootable_verified=False,
                abi_verified=False, metadata_sha256={name: hashlib.sha256(data).hexdigest()
                                                    for name, data in inputs.items()},
                requirements_sha256=hashlib.sha256(args.requirements.read_bytes()).hexdigest())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(plan, stream, indent=2)
        stream.write('\n')
    print(f'Planned {len(graph.paths)} loadable modules; ABI and hardware checks remain required.')


if __name__ == '__main__':
    main()
