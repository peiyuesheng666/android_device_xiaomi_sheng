#!/usr/bin/env python3
"""Offline two-file pystore vendor update preserving all parent metadata."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import uuid
from erofs_security_metadata import ErofsMetadata
from storage_guard import require_build_space
from export_source_built_binaries import sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('parent', 'payload', 'device', 'out', 'rom', 'host-tools'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--parent-sha256', required=True)
    args = parser.parse_args()
    parent, out = args.parent.resolve(strict=True), args.out.resolve()
    assert not out.exists()
    assert sha(parent) == args.parent_sha256
    payload_file = args.payload/'qualification.json'
    payload = json.loads(payload_file.read_text())
    assert payload['passed'] and payload['neverallow_checks_enabled']
    assert set(payload['payload']) == {'/etc/init/init.sheng.rc','/etc/selinux/vendor_sepolicy.cil'}
    replacements = {}
    for name,row in payload['payload'].items():
        path = Path(row['path']).resolve(strict=True)
        assert path.is_relative_to((args.payload/'payload').resolve())
        assert not Path(row['path']).is_symlink() and sha(path)==row['sha256']
        replacements[name] = path
    for name,digest in payload['source_sha256'].items():
        path = (args.device/name).resolve(strict=True)
        assert path.is_relative_to(args.device.resolve()) and sha(path)==digest
    for name,digest in payload['compiled_input_sha256'].items():
        assert sha(Path(name))==digest
    storage = require_build_space(out, minimum_output=1024**3)
    out.mkdir(parents=True)
    env = dict(os.environ, PATH=str(args.host_tools.resolve())+':'+os.environ['PATH'])
    commands = []

    def run(argv, label):
        p = subprocess.run(list(map(str, argv)), capture_output=True, env=env, timeout=240)
        (out/(label+'.stdout')).write_bytes(p.stdout)
        (out/(label+'.stderr')).write_bytes(p.stderr)
        commands.append(dict(label=label, argv=list(map(str, argv)), returncode=p.returncode))
        (out/'commands.json').write_text(json.dumps(commands, indent=2))
        p.check_returncode()
        return p.stdout

    avbpath = args.rom/'external/avb/avbtool.py'
    spec = importlib.util.spec_from_file_location('pystore_avb', avbpath)
    avb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(avb)

    def info(path):
        handler = avb.ImageHandler(str(path), read_only=True)
        try:
            return avb.Avb()._parse_image(handler)
        finally:
            handler._image.close()

    alias = out/'parent/vendor.img'
    alias.parent.mkdir()
    alias.symlink_to(parent)
    run([sys.executable,avbpath,'verify_image','--image',alias], 'parent-avb')
    root = out/'root'
    run(['fsck.erofs','--extract='+str(root),'--no-xattrs','--preserve',parent], 'extract-parent')

    def inventory(image, folder, label):
        reader = ErofsMetadata(image.read_bytes())
        rows = {}
        for p in [folder, *sorted(folder.rglob('*'))]:
            name = '/' if p == folder else '/'+p.relative_to(folder).as_posix()
            text = run(['dump.erofs','--path='+name,image], label+'-inode-'+str(len(rows))).decode()
            nid = int(re.search(r'NID:\s*(\d+)',text)[1])
            row = reader.inode(nid)
            row['nid'] = nid
            assert stat.S_ISREG(row['mode']) or stat.S_ISDIR(row['mode']) or stat.S_ISLNK(row['mode'])
            if p.is_symlink():
                assert stat.S_ISLNK(row['mode'])
                row['symlink_target_hex'] = os.fsencode(os.readlink(p)).hex()
            elif p.is_file():
                row['content_sha256'] = sha(p)
            rows[name] = row
        return rows

    original = inventory(parent, root, 'parent')
    (out/'parent-metadata.json').write_text(json.dumps(original,indent=2))
    assert original['/etc/init/init.sheng.rc']['content_sha256']==payload['original_vendor_rc_sha256']
    assert original['/etc/selinux/vendor_sepolicy.cil']['content_sha256']==payload['original_vendor_cil_sha256']
    hardlinks = {}
    for name,row in original.items():
        if stat.S_ISREG(row['mode']):
            hardlinks.setdefault(row['nid'],[]).append(name)
    for names in hardlinks.values():
        assert len(names)==original[names[0]]['links']
        first=root/names[0].lstrip('/')
        for name in names[1:]:
            other=root/name.lstrip('/')
            assert sha(first)==sha(other)
            if first.stat().st_ino!=other.stat().st_ino:
                other.unlink();os.link(first,other)
    contexts, changes = [], {}
    for name,row in original.items():
        p = root if name == '/' else root/name.lstrip('/')
        assert p.lstat().st_mode == row['mode']
        os.chown(p,row['uid'],row['gid'],follow_symlinks=False)
        assert 'security.selinux' in row['xattrs']
        assert set(row['xattrs']) <= {'security.selinux','security.capability'}
        for attr,value in row['xattrs'].items():
            if attr!='security.selinux':
                raw=bytes.fromhex(value)
                os.setxattr(p,attr,raw,follow_symlinks=False)
                assert os.getxattr(p,attr,follow_symlinks=False)==raw
        label = bytes.fromhex(row['xattrs']['security.selinux']).decode('ascii')
        assert re.fullmatch(r'u:object_r:[a-z0-9_]+:s0',label)
        contexts.append(re.escape('/vendor'+('' if name=='/' else name))+' '+label)
        if name in replacements:
            assert stat.S_ISREG(row['mode']) and row['links']==1
            replacement = replacements[name]
            assert replacement.is_file() and not replacement.is_symlink(), name
            before = p.stat()
            shutil.copyfile(replacement,p)
            os.utime(p,ns=(before.st_atime_ns,before.st_mtime_ns))
            changes[name] = sha(replacement)
    contextfile = out/'exact-parent-file-contexts'
    contextfile.write_text('\n'.join(contexts)+'\n')
    reader = ErofsMetadata(parent.read_bytes())
    candidate = out/'vendor.img'
    run(['mkfs.erofs','-zlz4hc,level=9','-C4096','-b4096','-T'+str(reader.build_time),
         '--mkfs-time','-U'+str(uuid.UUID(bytes=reader.uuid)),'--mount-point=vendor',
         '--file-contexts='+str(contextfile),candidate,root], 'mkfs')
    raw_bytes = candidate.stat().st_size
    _,header,descriptors,_ = info(parent)
    trees = [d for d in descriptors if isinstance(d,avb.AvbHashtreeDescriptor)]
    assert len(trees)==1 and header.algorithm_type==0 and header.flags==0
    tree = trees[0]
    assert tree.partition_name=='vendor' and tree.flags==0 and tree.dm_verity_version==1
    assert tree.data_block_size==tree.hash_block_size==4096 and tree.fec_num_roots==2

    def capacity(size):
        return int(run([sys.executable,avbpath,'add_hashtree_footer','--partition_size',size,
                        '--calc_max_image_size','--block_size',4096,'--fec_num_roots',2], 'capacity-'+str(size)))

    lo = (raw_bytes+4095)//4096*4096
    hi = max(parent.stat().st_size,(raw_bytes+1024**2+4095)//4096*4096)
    while capacity(hi)<raw_bytes:
        hi += (max(1024**2,raw_bytes//16)+4095)//4096*4096
        assert hi<=2*raw_bytes+1024**2, 'Unexpectedly large AVB overhead'
    while lo<hi:
        mid = (lo+hi)//8192*4096
        if capacity(mid)>=raw_bytes:
            hi=mid
        else:
            lo=mid+4096
    size = max(parent.stat().st_size,hi)
    cmd = [sys.executable,avbpath,'add_hashtree_footer','--image',candidate,
           '--partition_name','vendor','--partition_size',size,'--algorithm','NONE',
           '--salt',tree.salt.hex(),'--hash_algorithm',tree.hash_algorithm,'--block_size',4096,
           '--fec_num_roots',2,'--flags',header.flags,'--rollback_index',header.rollback_index,
           '--rollback_index_location',header.rollback_index_location]
    for d in descriptors:
        if isinstance(d,avb.AvbPropertyDescriptor):
            cmd += ['--prop',d.key+':'+d.value.decode()]
        else:
            assert isinstance(d,avb.AvbHashtreeDescriptor)
    run(cmd,'footer')
    run([sys.executable,avbpath,'verify_image','--image',candidate], 'candidate-avb')
    _,new_header,new_descriptors,_ = info(candidate)
    assert vars(header)==vars(new_header)
    newtree = next(d for d in new_descriptors if isinstance(d,avb.AvbHashtreeDescriptor))
    for key in ('partition_name','dm_verity_version','data_block_size','hash_block_size',
                'hash_algorithm','salt','fec_num_roots','flags'):
        assert getattr(tree,key)==getattr(newtree,key),key
    properties = lambda ds:[d.encode() for d in ds if not isinstance(d,avb.AvbHashtreeDescriptor)]
    assert properties(descriptors)==properties(new_descriptors)
    readback = out/'readback'
    run(['fsck.erofs','--extract='+str(readback),'--no-xattrs','--preserve',candidate], 'extract-candidate')
    after = inventory(candidate,readback,'candidate')
    assert set(after)==set(original)
    for name,row in original.items():
        for key in ('mode','uid','gid','links','xattrs'):
            assert after[name][key]==row[key],(name,key)
        if 'content_sha256' in row:
            assert after[name]['content_sha256']==changes.get(name,row['content_sha256']),name
        if 'symlink_target_hex' in row:
            assert after[name]['symlink_target_hex']==row['symlink_target_hex'],name
    def groups(rows):
        values={}
        for name,row in rows.items():
            if stat.S_ISREG(row['mode']):
                values.setdefault(row['nid'],[]).append(name)
        return sorted(sorted(names) for names in values.values())
    assert groups(after)==groups(original)
    assert set(changes)==set(replacements)
    assert sha(parent)==args.parent_sha256 and candidate.stat().st_size==size
    q = dict(passed=True,scope='offline vendor only',image=str(candidate),sha256=sha(candidate),
             bytes=size,raw_erofs_bytes=raw_bytes,source_parent_sha256=args.parent_sha256,
             payload_receipt_sha256=sha(payload_file),changed_paths=sorted(changes),
             entries=len(after),logical_partition_growth_bytes=size-parent.stat().st_size,
             exact_mode_ownership_links_and_security_xattrs_preserved=True,
             complete_content_inventory_verified=True,compression_and_hashtree_verified=True,
             original_parent_unchanged=True,filesystem_allocation_and_timestamps_compared=False,
             storage_preflight=storage,full_avb_chain_verified=False,runtime_verified=False,flashed=False)
    (out/'qualification.json').write_text(json.dumps(q,indent=2)+'\n')
    print(json.dumps(q,indent=2))


if __name__ == '__main__':
    main()
