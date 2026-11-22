#!/usr/bin/env python3
"""Offline remounter leaves from exact readback parents; never accesses a device.

Uses validated Android binary/policy outputs. Replaces four existing regular
files, preserving mode, UID/GID and exact SELinux xattr. Timestamps/allocation
are not compared. Full root-vbmeta chain and runtime acceptance stay pending.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile

from storage_guard import require_build_space

HERE = Path(__file__).resolve().parent
OWNED = HERE.parents[1] / 'interfaces/compat/overlay-remounter'


def sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''):
            result.update(chunk)
    return result.hexdigest()


def metadata(text):
    inode = re.search(r'Inode:\s+\d+\s+Type:\s+(\w+)\s+Mode:\s+(\d+)', text)
    owner = re.search(r'User:\s+(\d+)\s+Group:\s+(\d+)', text)
    links = re.search(r'Links:\s+(\d+)', text)
    attrs = re.findall(r'^  (\S+) \(\d+\) = ', text, re.M)
    if not inode or not owner or not links or inode[1] != 'regular' or int(links[1]) != 1:
        raise ValueError('Replacement requires a single-linked existing regular file')
    # Do not accidentally drop capabilities or other unfamiliar metadata.
    if attrs != ['security.selinux']:
        raise ValueError('Unexpected xattrs; refuse incomplete preservation')
    return dict(mode=inode[2], uid=int(owner[1]), gid=int(owner[2]), xattrs=attrs)


def dq(value):
    text = str(value)
    if any(c in text for c in ('\n', '\r', '\0')):
        raise ValueError('Unsafe debugfs command argument')
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def replace_hashtrees(descriptors, replacements, tree_type):
    result, seen = [], set()
    for descriptor in descriptors:
        if isinstance(descriptor, tree_type) and descriptor.partition_name in replacements:
            name = descriptor.partition_name
            if name in seen:
                raise ValueError('Duplicate parent partition descriptor')
            seen.add(name)
            result.append(replacements[name])
        else:
            result.append(descriptor)
    if seen != set(replacements):
        raise ValueError('Missing parent partition descriptor')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--backups', type=Path, required=True)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--policy', type=Path, required=True)
    parser.add_argument('--vbmeta-parents', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--qualify-existing-leaves', action='store_true',
                        help='Revalidate every existing leaf before finalizing a failed offline trial')
    args = parser.parse_args()
    rom = args.rom.resolve(strict=True)
    backups = args.backups.resolve(strict=True)
    binary = args.binary.resolve(strict=True)
    policy = args.policy.resolve(strict=True)
    parents = args.vbmeta_parents.resolve(strict=True)
    out = args.out.resolve()
    if out.exists() and not args.qualify_existing_leaves:
        parser.error('Preserve earlier trial; output must be new')
    if args.qualify_existing_leaves and (not out.is_dir() or (out / 'qualification.json').exists()):
        parser.error('Existing-leaf qualification requires an unfinished offline trial')
    storage = require_build_space(out, minimum_output=3 * 1024**3)
    backup_receipt = json.loads((backups / 'result.json').read_text())
    binary_receipt = json.loads((binary / 'qualification.json').read_text())
    policy_receipt = json.loads((policy / 'qualification.json').read_text())
    assert backup_receipt['passed'] and backup_receipt['physical_backing_only']
    assert binary_receipt['passed'] and not binary_receipt['test_only']
    assert binary_receipt['binary_sha256'] == sha(binary / 'overlay_remounter')
    assert binary_receipt['source_sha256'] == sha(OWNED / 'overlay_remounter.cpp')
    assert binary_receipt['header_sha256'] == sha(OWNED / 'mount_preserver.h')
    assert all(policy_receipt[k] for k in ('passed', 'neverallow_checks_enabled',
                                         'permissive_domains_unchanged', 'file_contexts_checked'))
    assert policy_receipt['system_ext_cil_sha256'] == sha(policy / 'system_ext_sepolicy.cil')
    assert policy_receipt['policy_source_sha256'] == sha(
        OWNED / 'sepolicy/system_ext/private/sheng_overlay_remounter.te')
    contexts_source = OWNED / 'sepolicy/system_ext/private/file_contexts'
    assert policy_receipt['file_contexts_source_sha256'] == sha(contexts_source)
    avbpath = rom / 'external/avb/avbtool.py'
    spec = importlib.util.spec_from_file_location('avb', avbpath)
    avb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(avb)
    host = rom / 'out-clean-ota-20261116/host/linux-x86/bin'
    environment = dict(os.environ, PATH=str(host) + ':' + os.environ['PATH'])
    assert (host / 'fec').is_file(), 'Preserve the parent FEC; do not omit it to get a pass'
    out.mkdir(parents=True, exist_ok=args.qualify_existing_leaves)
    suffix = '-finalize' if args.qualify_existing_leaves else ''
    logs, payload = (out / (x + suffix) for x in ('logs', 'payload'))
    images = out / 'images'
    for p in (logs, payload):
        p.mkdir()
    images.mkdir(exist_ok=args.qualify_existing_leaves)
    commands = []

    def run(command, label):
        p = subprocess.run([str(x) for x in command], capture_output=True, timeout=240,
                           env=environment, cwd=rom)
        (logs / (label + '.stdout')).write_bytes(p.stdout)
        (logs / (label + '.stderr')).write_bytes(p.stderr)
        commands.append(dict(label=label, command=[str(x) for x in command], returncode=p.returncode))
        (out / ('commands' + suffix + '.json')).write_text(json.dumps(commands, indent=2))
        if p.returncode:
            raise RuntimeError(f'{label} failed; see {logs}')
        return p.stdout

    def info(image):
        handler = avb.ImageHandler(str(image), read_only=True)
        try:
            return avb.Avb()._parse_image(handler)
        finally:
            handler._image.close()

    def debug(image, command, label, write=False):
        output = run([host / 'debugfs_static', *(['-w'] if write else []), '-R', command, image], label)
        # debugfs often exits zero on command errors. All reads/writes below
        # additionally have exact file-content and metadata postconditions.
        errors = (logs / (label + '.stderr')).read_text(errors='replace').lower()
        if any(x in errors for x in ('not found', 'error', 'could not', 'no space')):
            raise RuntimeError('debugfs diagnostic failure: ' + label)
        return output

    original_hashes = {}
    # avbtool resolves descriptor partitions by <partition>.img beside the
    # supplied image. Do not mistake a missing filename alias for corrupt data.
    with tempfile.TemporaryDirectory(prefix='sheng-parent-avb-', dir='/dev/shm') as td:
        for name in ('system', 'system_ext'):
            parent = backups / (name + '_b.physical-backing.img')
            record = backup_receipt['partitions'][name + '_b']
            original_hashes[name] = sha(parent)
            assert original_hashes[name] == record['sha256'] and parent.stat().st_size == record['bytes']
            alias = Path(td) / (name + '.img')
            alias.symlink_to(parent)
            run(['python3', avbpath, 'verify_image', '--image', alias], name + '-parent-hashtree')

    ext_parent = backups / 'system_ext_b.physical-backing.img'
    for name in ('system_ext_sepolicy.cil', 'system_ext_file_contexts',
                 'system_ext_sepolicy_and_mapping.sha256', 'mapping/202604.cil'):
        target = payload / ('baseline-' + name.replace('/', '-'))
        debug(ext_parent, 'dump ' + dq('/etc/selinux/' + name) + ' ' + dq(target),
              'extract-' + name.replace('/', '-'))
        assert target.is_file()
    mapping = (payload / 'baseline-mapping-202604.cil').read_bytes()
    old_cil = (payload / 'baseline-system_ext_sepolicy.cil').read_bytes()
    old_sidecar = (payload / 'baseline-system_ext_sepolicy_and_mapping.sha256').read_text().strip()
    assert hashlib.sha256(old_cil + mapping).hexdigest() == old_sidecar
    new_cil = (policy / 'system_ext_sepolicy.cil').read_bytes()
    sidecar = hashlib.sha256(new_cil + mapping).hexdigest()
    assert sidecar != old_sidecar
    (payload / 'system_ext_sepolicy.cil').write_bytes(new_cil)
    (payload / 'system_ext_sepolicy_and_mapping.sha256').write_text(sidecar + '\n')
    contexts = (payload / 'baseline-system_ext_file_contexts').read_bytes()
    assert b'sheng_overlay_staging_file' not in contexts
    (payload / 'system_ext_file_contexts').write_bytes(contexts.rstrip() + b'\n' + contexts_source.read_bytes())
    replacements = {
        'system': {'/system/xbin/overlay_remounter': binary / 'overlay_remounter'},
        'system_ext': {'/etc/selinux/' + name: payload / name for name in
                       ('system_ext_sepolicy.cil', 'system_ext_sepolicy_and_mapping.sha256',
                        'system_ext_file_contexts')},
    }
    results = {}
    for name, files in replacements.items():
        parent = backups / (name + '_b.physical-backing.img')
        _, header, descriptors, _ = info(parent)
        trees = [d for d in descriptors if isinstance(d, avb.AvbHashtreeDescriptor)]
        assert len(trees) == 1 and header.algorithm_type == 0 and header.flags == 0
        tree = trees[0]
        assert tree.partition_name == name and tree.flags == 0 and tree.dm_verity_version == 1
        assert tree.data_block_size == tree.hash_block_size == 4096 and tree.fec_num_roots == 2
        image = images / (name + '.img')
        if not args.qualify_existing_leaves:
            shutil.copyfile(parent, image)
            run(['python3', avbpath, 'erase_footer', '--image', image], name + '-erase-candidate-footer')
            assert image.stat().st_size == tree.image_size
        else:
            assert image.is_file() and image.stat().st_size == parent.stat().st_size
        verified = []
        for index, (path, replacement) in enumerate(files.items()):
            label = f'{name}-{index}'
            before = metadata(debug(parent, 'stat ' + dq(path), label + '-before-stat').decode())
            attr = payload / (label + '.selinux')
            debug(parent, 'ea_get -f ' + dq(attr) + ' ' + dq(path) + ' security.selinux', label + '-get-label')
            assert attr.is_file() and attr.read_bytes().startswith(b'u:object_r:')
            if not args.qualify_existing_leaves:
                debug(image, 'rm ' + dq(path), label + '-remove', write=True)
                debug(image, 'write ' + dq(replacement) + ' ' + dq(path), label + '-write', write=True)
                for field, value in [('uid', before['uid']), ('gid', before['gid']),
                                     ('mode', '010' + before['mode'])]:
                    debug(image, 'set_inode_field ' + dq(path) + ' ' + field + ' ' + str(value),
                          label + '-set-' + field, write=True)
                debug(image, 'ea_set -f ' + dq(attr) + ' ' + dq(path) + ' security.selinux', label + '-set-label', write=True)
            after = metadata(debug(image, 'stat ' + dq(path), label + '-after-stat').decode())
            assert before == after
            readback = payload / (label + '.readback')
            debug(image, 'dump ' + dq(path) + ' ' + dq(readback), label + '-readback')
            assert sha(readback) == sha(replacement)
            attr_after = payload / (label + '.selinux-after')
            debug(image, 'ea_get -f ' + dq(attr_after) + ' ' + dq(path) + ' security.selinux', label + '-label-readback')
            assert attr_after.read_bytes() == attr.read_bytes()
            verified.append(dict(path=path, sha256=sha(replacement), metadata=before,
                                 selinux_xattr_sha256=sha(attr), readback_verified=True))
        command = ['python3', avbpath, 'add_hashtree_footer', '--image', image,
                   '--partition_size', parent.stat().st_size, '--partition_name', name,
                   '--algorithm', 'NONE', '--salt', tree.salt.hex(), '--hash_algorithm', tree.hash_algorithm,
                   '--block_size', tree.data_block_size, '--fec_num_roots', tree.fec_num_roots,
                   '--flags', header.flags, '--rollback_index', header.rollback_index,
                   '--rollback_index_location', header.rollback_index_location]
        for d in descriptors:
            if isinstance(d, avb.AvbPropertyDescriptor):
                command += ['--prop', d.key + ':' + d.value.decode()]
            else:
                assert isinstance(d, avb.AvbHashtreeDescriptor)
        if not args.qualify_existing_leaves:
            run(command, name + '-new-footer')
        run(['python3', avbpath, 'verify_image', '--image', image], name + '-candidate-hashtree')
        _, new_header, new_descriptors, _ = info(image)
        assert vars(header) == vars(new_header)
        new_tree = next(d for d in new_descriptors if isinstance(d, avb.AvbHashtreeDescriptor))
        before_tree, after_tree = vars(tree).copy(), vars(new_tree).copy()
        assert before_tree.pop('root_digest') != after_tree.pop('root_digest')
        assert before_tree == after_tree
        assert [d.encode() for d in descriptors if not isinstance(d, avb.AvbHashtreeDescriptor)] == [
            d.encode() for d in new_descriptors if not isinstance(d, avb.AvbHashtreeDescriptor)]
        assert image.stat().st_size == parent.stat().st_size
        results[name] = dict(path=str(image), bytes=image.stat().st_size, sha256=sha(image),
                             parent_sha256=original_hashes[name], replacements=verified,
                             standalone_hashtree_verified=True)

    parent = parents / 'vbmeta_system.img'
    assert sha(parent) == 'cb5d5713bb5669d867b70b19cbe4abcf4eb33b5f4e07ef32b8918d07569543eb'
    _, header, descriptors, _ = info(parent)
    assert header.flags == 0 and header.algorithm_type == 1 and header.rollback_index == 1
    vbmeta = images / 'vbmeta_system.img'
    replacement_trees = {}
    for name in ('system', 'system_ext'):
        _, _, leaves, _ = info(images / (name + '.img'))
        replacement_trees[name] = next(d for d in leaves if isinstance(d, avb.AvbHashtreeDescriptor))
    exact_descriptors = replace_hashtrees(descriptors, replacement_trees, avb.AvbHashtreeDescriptor)
    assert header.public_key_metadata_size == 0
    # --include_descriptors_from_image also appends property descriptors.
    # Importing the parent plus both leaves duplicates six properties. Use the
    # official generator with the exact in-place-replaced descriptor sequence.
    blob = avb.Avb()._generate_vbmeta_blob(
        algorithm_name='SHA256_RSA2048',
        key_path=str(rom / 'external/avb/test/data/testkey_rsa2048.pem'),
        public_key_metadata_path=None, descriptors=exact_descriptors,
        chain_partitions_use_ab=None, chain_partitions_do_not_use_ab=None,
        rollback_index=header.rollback_index, flags=0,
        rollback_index_location=header.rollback_index_location,
        props=None, props_from_file=None, kernel_cmdlines=None,
        setup_rootfs_from_kernel=None, ht_desc_to_setup=None,
        include_descriptors_from_image=None, signing_helper=None,
        signing_helper_with_files=None, release_string=header.release_string,
        append_to_release_string=None,
        required_libavb_version_minor=header.required_libavb_version_minor)
    assert len(blob) <= parent.stat().st_size
    if vbmeta.exists():
        rejected = out / 'rejected-vbmeta_system.img'
        assert not rejected.exists()
        shutil.copyfile(vbmeta, rejected)
    vbmeta.write_bytes(blob + b'\0' * (parent.stat().st_size - len(blob)))
    _, new_header, new_descriptors, _ = info(vbmeta)
    assert vars(header) == vars(new_header)
    assert avb.verify_vbmeta_signature(new_header, vbmeta.read_bytes())
    def public_key(image, hdr):
        start = hdr.SIZE + hdr.authentication_data_block_size + hdr.public_key_offset
        return image.read_bytes()[start:start + hdr.public_key_size]
    assert public_key(parent, header) == public_key(vbmeta, new_header)
    assert hashlib.sha1(public_key(vbmeta, new_header)).hexdigest() == 'cdbb77177f731920bbe0a0f94f84d9038ae0617d'
    preserved = lambda ds: [d.encode() for d in ds if not (
        isinstance(d, avb.AvbHashtreeDescriptor) and d.partition_name in ('system', 'system_ext'))]
    assert preserved(descriptors) == preserved(new_descriptors)
    assert vbmeta.stat().st_size == parent.stat().st_size
    assert all(sha(backups / (name + '_b.physical-backing.img')) == digest
               for name, digest in original_hashes.items())
    receipt = dict(passed=True, storage_preflight=storage, images=results,
                   vbmeta_system=dict(path=str(vbmeta), sha256=sha(vbmeta), signed_structure_verified=True,
                                      only_system_system_ext_descriptors_changed=True, flags=0),
                   original_parents_unchanged=True, exact_file_payload_and_security_metadata_verified=True,
                   timestamps_and_allocation_compared=False, whole_filesystem_inventory_compared=False,
                   candidate_system_ext_policy_sidecar=sidecar,
                   root_vbmeta_descriptor_reconciliation_pending=True, installed_root_flags_still_3=True,
                   full_avb_chain_verified=False, snapshot_composed_runtime_verified=False,
                   actual_product_soong_build_verified=False, android_runtime_verified=False,
                   device_access=False, flashed=False)
    (out / 'qualification.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
