#!/usr/bin/env python3
"""Read current Recovery b physical companions without maps, mounts or writes.

Validates liblp geometry/header/table checksums, explicitly selecting slot 1.
Physical backing is NOT snapshot-composed runtime evidence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import re
from storage_guard import require_build_space
from export_source_built_binaries import sha


def parse_slot(data, super_bytes, slot=1):
    def checksum(blob, offset):
        expected=blob[offset:offset+32]
        assert hashlib.sha256(blob[:offset]+bytes(32)+blob[offset+32:]).digest()==expected

    geom=data[4096:8192]
    magic,size=struct.unpack_from('<II',geom)
    assert magic==0x616c4467 and 52<=size<=4096
    checksum(geom[:size],8)
    assert geom[:size]==data[8192:8192+size]
    maximum,slots,block_size=struct.unpack_from('<III',geom,40)
    assert 0<=slot<slots and maximum%4096==0
    start=12288+slot*maximum
    magic,major,minor,header_size=struct.unpack_from('<IHHI',data,start)
    assert magic==0x414c5030 and major==10 and minor<=2 and 128<=header_size<=maximum
    header=data[start:start+header_size]
    assert len(header)==header_size
    checksum(header,12)
    table_size=struct.unpack_from('<I',header,44)[0]
    assert header_size+table_size<=maximum
    tables=data[start+header_size:start+header_size+table_size]
    assert hashlib.sha256(tables).digest()==header[48:80]
    backup=12288+(slots+slot)*maximum
    assert data[backup:backup+header_size+table_size]==header+tables

    def table(offset,width):
        first,count,actual=struct.unpack_from('<III',header,offset)
        assert actual==width and first+count*width<=len(tables)
        return [tables[first+i*width:first+(i+1)*width] for i in range(count)]

    def name(raw):
        value=raw.split(b'\0')[0].decode('ascii')
        assert re.fullmatch(r'[A-Za-z0-9_.-]+',value),value
        return value

    extents=[dict(zip(('sectors','type','sector','source'),struct.unpack('<QIQI',e))) for e in table(92,24)]
    devices=table(116,64)
    assert len(devices)==1
    first_sector,alignment,alignment_offset,device_bytes,raw,flags=struct.unpack('<QIIQ36sI',devices[0])
    assert device_bytes==super_bytes and name(raw)=='super' and first_sector>=2048
    groups=[]
    for e in table(104,48):
        raw,flags,maximum_size=struct.unpack('<36sIQ',e)
        groups.append(dict(name=name(raw),flags=flags,maximum_size=maximum_size))
    partitions=[]
    for e in table(80,52):
        raw,attributes,first,count,group=struct.unpack('<36s4I',e)
        assert first+count<=len(extents) and group<len(groups)
        selected=extents[first:first+count]
        for extent in selected:
            assert extent['source']==0 and extent['type'] in (0,1)
            if extent['type']==0:
                assert extent['sector']>=first_sector and (extent['sector']+extent['sectors'])*512<=super_bytes
        partitions.append(dict(name=name(raw),attributes=attributes,group=group,
                               bytes=sum(e['sectors']*512 for e in selected),extents=selected))
    assert len({p['name'] for p in partitions})==len(partitions)
    return dict(super_bytes=super_bytes,metadata_slots=slots,metadata_slot=slot,
                logical_block_size=block_size,groups=groups,partitions=partitions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--partition', choices=('vendor','system','system_ext','product','odm'),
                        action='append', required=True)
    args = parser.parse_args()
    assert len(set(args.partition)) == len(args.partition)
    out = args.out.resolve()
    assert not out.exists()
    prefix = [str(args.adb.resolve(strict=True)), '-s', 'ca10ede3']

    def read(command, timeout=45):
        return subprocess.check_output(prefix+['exec-out',command],timeout=timeout)

    def identity():
        return read('getprop ro.serialno; getprop ro.product.device; getprop ro.boot.slot_suffix; '
                    'getprop init.svc.recovery; id -u; cat /proc/sys/kernel/random/boot_id').decode().replace('\r','').strip().splitlines()

    before = identity()
    assert len(before)==6 and before[:5]==['ca10ede3','sheng','_b','running','0']
    metadata_command = 'dd if=/dev/block/by-name/super bs=1048576 count=1 2>/dev/null'
    data = read(metadata_command)
    assert len(data)==1024**2
    super_bytes = int(read('blockdev --getsize64 /dev/block/by-name/super'))
    layout = parse_slot(data,super_bytes,slot=1)
    plans = {}
    for name in args.partition:
        rows = [r for r in layout['partitions'] if r['name']==name+'_b']
        assert len(rows)==1 and rows[0]['bytes']>0
        row=rows[0]
        end=0;physical=[]
        for e in row['extents']:
            assert e['type']==0 and e['source']==0 and e['sectors']>0 and e['sector']>=2048
            start,size=e['sector']*512,e['sectors']*512
            assert start+size<=super_bytes
            assert not any(start<b and a<start+size for a,b in physical)
            physical.append((start,start+size));end+=size
        assert end==row['bytes']
        plans[name]=row
    storage=require_build_space(out,minimum_output=sum(r['bytes'] for r in plans.values())+1024**3)
    out.mkdir(parents=True)
    (out/'super-metadata.bin').write_bytes(data)
    (out/'layout.json').write_text(json.dumps(layout,indent=2)+'\n')
    state=dict(passed=False,scope='Recovery physical backing only',physical_backing_only=True,
               snapshot_composed_runtime_verified=False,device_partition_writes=False,
               device_mapper_changes=False,device_mount_changes=False,flashed=False,
               identity=before,metadata_sha256=hashlib.sha256(data).hexdigest(),
               metadata_slot=1,storage_preflight=storage,partitions={})

    def save():
        (out/'capture.json').write_text(json.dumps(state,indent=2)+'\n')

    save()
    for name,row in plans.items():
        print('capturing',name,row['bytes'],flush=True)
        partial=out/(name+'.img.partial')
        with partial.open('xb') as stream:
            for index,e in enumerate(row['extents']):
                size=e['sectors']*512
                command=('dd if=/dev/block/by-name/super bs=1048576 iflag=skip_bytes,count_bytes '
                         f'skip={e["sector"]*512} count={size} 2>/dev/null')
                start=stream.tell()
                p=subprocess.run(prefix+['exec-out',command],stdout=stream,stderr=subprocess.PIPE,timeout=300)
                (out/(name+'-extent-'+str(index)+'.stderr')).write_bytes(p.stderr)
                p.check_returncode()
                assert stream.tell()-start==size
        assert partial.stat().st_size==row['bytes']
        assert read(metadata_command)==data and identity()==before
        image=out/(name+'.img');partial.rename(image)
        state['partitions'][name]=dict(path=str(image),sha256=sha(image),bytes=row['bytes'],
                                      attributes=row['attributes'],extents=row['extents'])
        save()
    assert read(metadata_command)==data and identity()==before
    state.update(passed=True,metadata_unchanged=True,identity_unchanged=True)
    save()
    print('capture_complete',flush=True)


if __name__=='__main__':
    main()
