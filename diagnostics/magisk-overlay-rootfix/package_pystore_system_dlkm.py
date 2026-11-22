#!/usr/bin/env python3
"""Offline matched ext4 system_dlkm update preserving exact parent metadata."""
from pathlib import Path
import argparse, hashlib, importlib.util, json, os, re, shutil, subprocess, sys
from package_remounter_trial import dq, metadata, sha
from storage_guard import require_build_space
parser = argparse.ArgumentParser(description=__doc__)
for name in ('parent','stage','audit','out','rom','host-tools'):
    parser.add_argument('--'+name,type=Path,required=True)
parser.add_argument('--parent-sha256',required=True)
args=parser.parse_args()
parent=args.parent.resolve(strict=True)
stage=args.stage.resolve(strict=True)
out=args.out.resolve()
rom=args.rom.resolve(strict=True)
host=args.host_tools.resolve(strict=True)
assert not out.exists()
record=dict(sha256=args.parent_sha256,bytes=parent.stat().st_size)
assert sha(parent)==record['sha256']
storage=require_build_space(out,minimum_output=64*1024**2)
audit=json.loads(args.audit.read_text())
assert audit['passed'] and sha(stage/'prepared.json')==audit['prepared_sha256']
prepared=json.loads((stage/'prepared.json').read_text())
modules=stage/'system_dlkm/lib/modules/android17-6.18'
names = {'zram.ko', 'zsmalloc.ko'}
assert {p.name for p in modules.glob('*.ko')} == names
for name in names:
    rows = [r for r in prepared['modules'].values() if r['filename'] == name]
    assert rows and all(sha(modules / name) == r['packaged_sha256'] for r in rows)
# Preserve the parent's flat loader paths. Do not introduce a version subdir
# or unnecessary builtin inventories absent from this existing filesystem.
assert (modules / 'modules.dep').read_text().splitlines() == ['zram.ko: zsmalloc.ko', 'zsmalloc.ko:']
assert (modules / 'modules.load').read_text().splitlines() == ['zsmalloc.ko', 'zram.ko']
replacements = { '/lib/modules/' + name: modules / name for name in
                 sorted(names | {'modules.dep', 'modules.load', 'modules.alias', 'modules.softdep'}) }
out.mkdir(parents=True)
logs = out / 'logs'
logs.mkdir()
payload = out / 'payload'
payload.mkdir()
commands = []
env = dict(os.environ, PATH=str(host) + ':' + os.environ['PATH'])

def run(argv, label):
    p = subprocess.run(list(map(str, argv)), env=env, capture_output=True, timeout=240)
    (logs / (label + '.stdout')).write_bytes(p.stdout)
    (logs / (label + '.stderr')).write_bytes(p.stderr)
    commands.append(dict(label=label, argv=list(map(str, argv)), returncode=p.returncode))
    (out / 'commands.json').write_text(json.dumps(commands, indent=2))
    p.check_returncode()
    return p.stdout

def debug(image, command, label, write=False):
    result = run([host / 'debugfs_static', *(['-w'] if write else []), '-R', command, image], label)
    errors = (logs / (label + '.stderr')).read_text(errors='replace').lower()
    if any(x in errors for x in ('not found', 'error', 'could not', 'no space', 'usage:')):
        raise RuntimeError('debugfs failure: ' + label)
    return result

avbpath = rom / 'external/avb/avbtool.py'
spec = importlib.util.spec_from_file_location('system_dlkm_avb', avbpath)
avb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(avb)

def info(path):
    handler = avb.ImageHandler(str(path), read_only=True)
    try:
        return avb.Avb()._parse_image(handler)
    finally:
        handler._image.close()

alias = out / 'parent/system_dlkm.img'
alias.parent.mkdir()
alias.symlink_to(parent)
run([sys.executable, avbpath, 'verify_image', '--image', alias], 'parent-avb')
_, header, descriptors, _ = info(parent)
trees = [d for d in descriptors if isinstance(d, avb.AvbHashtreeDescriptor)]
assert len(trees) == 1 and header.algorithm_type == 0 and header.flags == 0
tree = trees[0]
assert tree.partition_name == 'system_dlkm' and tree.flags == 0 and tree.dm_verity_version == 1
assert tree.data_block_size == tree.hash_block_size == 4096 and tree.fec_num_roots == 2
image = out / 'system_dlkm.img'
shutil.copyfile(parent, image)
run([sys.executable, avbpath, 'erase_footer', '--image', image], 'erase-footer')
assert image.stat().st_size == tree.image_size
original = out / 'original-files'
original.mkdir()
debug(parent, 'rdump / ' + dq(original), 'parent-inventory')
paths = ['/', *['/' + p.relative_to(original).as_posix() for p in sorted(original.rglob('*'))]]
assert set(replacements) <= set(paths)
assert {p for p in paths if p.endswith('.ko')} == {'/lib/modules/' + n for n in names}

def inventory(source, prefix):
    rows = {}
    for index, path in enumerate(paths):
        key = prefix + '-' + str(index)
        text = debug(source, 'stat ' + dq(path), key + '-stat').decode()
        inode = re.search(r'Inode:\s+\d+\s+Type:\s+(\w+)\s+Mode:\s+(\d+)', text)
        owner = re.search(r'User:\s+(\d+)\s+Group:\s+(\d+)', text)
        links = re.search(r'Links:\s+(\d+)', text)
        assert inode and owner and links and inode[1] in ('regular', 'directory')
        attrs = re.findall(r'^  (\S+) \(\d+\) = ', text, re.M)
        assert attrs == ['security.selinux'], (path, attrs)
        attr = payload / (key + '.selinux')
        debug(source, 'ea_get -f ' + dq(attr) + ' ' + dq(path) + ' security.selinux', key + '-label')
        assert attr.read_bytes().startswith(b'u:object_r:')
        row = dict(type=inode[1], mode=inode[2], uid=int(owner[1]), gid=int(owner[2]),
                   links=int(links[1]), xattrs={'security.selinux': attr.read_bytes().hex()})
        if inode[1] == 'regular':
            assert row['links'] == 1
            dump = payload / (key + '.file')
            debug(source, 'dump ' + dq(path) + ' ' + dq(dump), key + '-dump')
            row['sha256'] = sha(dump)
        rows[path] = row
    return rows

before = inventory(parent, 'before')
for index, (path, replacement) in enumerate(replacements.items()):
    key = 'replace-' + str(index)
    row = before[path]
    metadata(debug(parent, 'stat ' + dq(path), key + '-assert-regular').decode())
    debug(image, 'rm ' + dq(path), key + '-remove', True)
    debug(image, 'write ' + dq(replacement) + ' ' + dq(path), key + '-write', True)
    for field, value in [('uid', row['uid']), ('gid', row['gid']), ('mode', '010' + row['mode'])]:
        debug(image, 'set_inode_field ' + dq(path) + ' ' + field + ' ' + str(value), key + '-' + field, True)
    attr = payload / (key + '.label')
    attr.write_bytes(bytes.fromhex(row['xattrs']['security.selinux']))
    debug(image, 'ea_set -f ' + dq(attr) + ' ' + dq(path) + ' security.selinux', key + '-label', True)
run([host / 'e2fsck', '-f', '-n', image], 'filesystem-check')
after = inventory(image, 'after')
for path, row in before.items():
    expected = dict(row)
    if path in replacements:
        expected['sha256'] = sha(replacements[path])
    assert after[path] == expected, path
readback = out / 'readback-files'
readback.mkdir()
debug(image, 'rdump / ' + dq(readback), 'candidate-inventory')
assert {p.relative_to(original).as_posix() for p in original.rglob('*')} == {
    p.relative_to(readback).as_posix() for p in readback.rglob('*')}
cmd = [sys.executable, avbpath, 'add_hashtree_footer', '--image', image,
       '--partition_size', parent.stat().st_size, '--partition_name', 'system_dlkm',
       '--algorithm', 'NONE', '--salt', tree.salt.hex(), '--hash_algorithm', tree.hash_algorithm,
       '--block_size', tree.data_block_size, '--fec_num_roots', tree.fec_num_roots,
       '--flags', header.flags, '--rollback_index', header.rollback_index,
       '--rollback_index_location', header.rollback_index_location]
for d in descriptors:
    if isinstance(d, avb.AvbPropertyDescriptor):
        cmd += ['--prop', d.key + ':' + d.value.decode()]
    else:
        assert isinstance(d, avb.AvbHashtreeDescriptor)
run(cmd, 'new-footer')
run([sys.executable, avbpath, 'verify_image', '--image', image], 'candidate-avb')
_, new_header, new_descriptors, _ = info(image)
assert vars(header) == vars(new_header)
new_tree = next(d for d in new_descriptors if isinstance(d, avb.AvbHashtreeDescriptor))
a, b = vars(tree).copy(), vars(new_tree).copy()
assert a.pop('root_digest') != b.pop('root_digest') and a == b
assert [d.encode() for d in descriptors if not isinstance(d, avb.AvbHashtreeDescriptor)] == [
    d.encode() for d in new_descriptors if not isinstance(d, avb.AvbHashtreeDescriptor)]
assert sha(parent) == record['sha256'] and image.stat().st_size == parent.stat().st_size
q = dict(passed=True, scope='offline system_dlkm only', image=str(image), sha256=sha(image),
         bytes=image.stat().st_size, parent_sha256=record['sha256'], module_count=2,
         module_stage_receipt_sha256=sha(stage / 'prepared.json'), entries=len(paths),
         replacements={p: sha(s) for p, s in replacements.items()},
         flat_loader_paths_preserved=True, complete_content_inventory_verified=True,
         exact_mode_ownership_links_and_security_xattrs_preserved=True,
         filesystem_check_passed=True, standalone_hashtree_verified=True,
         logical_partition_growth_required=False, filesystem_allocation_and_timestamps_compared=False,
         full_avb_chain_verified=False, runtime_verified=False, flashed=False, storage_preflight=storage)
(out / 'qualification.json').write_text(json.dumps(q, indent=2))
(out / 'inventory.json').write_text(json.dumps(dict(before=before, after=after), indent=2))
print(json.dumps(q,indent=2))
