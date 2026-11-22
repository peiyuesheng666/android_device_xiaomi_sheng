#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Constrain HID labeling changes and review every permission of their new type."""
import copy
from pathlib import Path
import re

from review_sheng_policy_delta import Policy, frozen

TYPE = 'vendor_sysfs_sheng_hid'
PATHS = tuple('/devices/0006:15D9:00A' + str(index) + '.' for index in range(1, 5))
READ_ACCESS = {'dir': ('getattr', 'open', 'read', 'search'),
               'file': ('getattr', 'open', 'read'), 'lnk_file': ('getattr', 'read')}
CHANGES = {
    'sepolicy/vendor/file.te': ([], ['type ' + TYPE + ', fs_type, sysfs_type;']),
    'sepolicy/vendor/genfs_contexts': ([], [
        'genfscon sysfs ' + path + ' u:object_r:' + TYPE + ':s0' for path in PATHS]),
    'sepolicy/vendor/system_server.te': ([], [
        'allow system_server ' + TYPE + ':' + kind + ' { ' + ' '.join(permissions) + ' };'
        for kind, permissions in READ_ACCESS.items()]),
}


def involving(policy, name):
    """Expand only AV rules involving this one type, not the complete graph."""
    rows = set()
    for form in policy.forms:
        if form[0] not in ('allow', 'auditallow', 'dontaudit'):
            continue
        kind, source, target, (tclass, permissions) = form
        sources = policy.members(source)
        if target == 'self':
            if name in sources:
                rows.update((kind, 'sysfs', 'sysfs', tclass, permission) for permission in permissions)
            continue
        targets = policy.members(target)
        if name in sources:
            # Normalize the dedicated type to its former sysfs label. The
            # filesystem itself and all unrelated inode labels stay intact.
            rows.update((kind, 'sysfs', 'sysfs' if target == name else target,
                         tclass, permission)
                        for target in targets for permission in permissions)
        if name in targets:
            rows.update((kind, 'sysfs' if source == name else source, 'sysfs', tclass, permission)
                        for source in sources for permission in permissions)
    return rows


def non_av_involving(policy, name):
    rows = set()
    for form in policy.forms:
        if form[0] not in ('allowx', 'auditallowx', 'dontauditx', 'typetransition', 'typechange', 'typemember'):
            continue
        kind, source, target = form[:3]
        payload = frozen(form[3:])
        sources = policy.members(source)
        if target == 'self':
            if name in sources:
                rows.add((kind, 'sysfs', 'sysfs', payload))
            continue
        targets = policy.members(target)
        if name in sources:
            rows.update((kind, 'sysfs', 'sysfs' if target == name else target, payload) for target in targets)
        if name in targets:
            rows.update((kind, 'sysfs' if source == name else source, 'sysfs', payload) for source in sources)
    return rows


def check_review(review, expected):
    assert not expected and review['added_types'] == [TYPE]
    for key in ('removed_types', 'added_existing_type_permissions', 'removed_existing_type_permissions',
                'existing_type_attribute_membership_changes', 'existing_type_non_av_rule_forms_added',
                'existing_type_non_av_rule_forms_removed', 'existing_role_type_statements_added',
                'existing_role_type_statements_removed', 'other_statements_removed'):
        assert not review[key], (key, review[key])
    assert review['baseline_permissive_domains'] == review['candidate_permissive_domains']
    paths = list(map(Path, review['inputs_and_decompiled_sha256']))
    baseline = Policy(next(path for path in paths if path.name == 'baseline.cil'))
    candidate = Policy(next(path for path in paths if path.name == 'candidate.cil'))
    attributes = {name for name in candidate.attributes
                  if not name.startswith('base_typeattr_') and TYPE in candidate.members(name)}
    assert {'fs_type', 'sysfs_type'} <= attributes
    assert all(re.fullmatch(r'(fs_type|sysfs_type)(_[0-9]+)?', name) for name in attributes), attributes
    expected_access = {('allow', 'system_server', 'sysfs', kind, permission)
                       for kind, permissions in READ_ACCESS.items() for permission in permissions}
    before, after = involving(baseline, 'sysfs'), involving(candidate, TYPE)
    assert expected_access <= after, sorted(expected_access - after)
    # Existing generic fs_type/sysfs_type permissions are inherited. The only
    # additional access relative to the former sysfs label is the reader above.
    assert after - before <= expected_access, sorted((after - before) - expected_access)
    assert not any(row[0] == 'allow' and row[1] == 'system_server'
                   and row[4] in ('write', 'append', 'create', 'unlink', 'setattr') for row in after)
    assert non_av_involving(candidate, TYPE) <= non_av_involving(baseline, 'sysfs')
    assert not any(form[0] in ('typetransition', 'typechange', 'typemember') and form[-1] == TYPE
                   for form in candidate.forms)
    template = next(form for form in baseline.forms
                    if form[0] == 'genfscon' and form[1] == 'sysfs' and form[2].strip('"') == '/')
    expected_contexts = set()
    for path in PATHS:
        form = copy.deepcopy(template)
        form[2] = '"' + path + '"'
        form[-1][2] = TYPE
        expected_contexts.add(frozen(form))
    assert {frozen(form) for form in review['other_statements_added']} == expected_contexts
