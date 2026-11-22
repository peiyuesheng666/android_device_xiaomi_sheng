#!/usr/bin/env python3
"""Back up current boot-family bytes in Recovery; no reboot, flash or slot change."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from export_source_built_binaries import sha
from storage_guard import require_build_space


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    prefix=[str(args.adb.resolve(strict=True)),'-s','ca10ede3']
    out=args.out.resolve()
    assert not out.exists()

    def read(cmd):
        return subprocess.check_output(prefix+['exec-out',cmd],timeout=45)

    def identity():
        return read('getprop ro.serialno; getprop ro.product.device; getprop ro.boot.slot_suffix; '
                    'getprop init.svc.recovery; id -u; cat /proc/sys/kernel/random/boot_id').decode().replace('\r','').strip().splitlines()

    before=identity()
    assert len(before)==6 and before[:5]==['ca10ede3','sheng','_b','running','0']
    metadata=read('dd if=/dev/block/by-name/super bs=1048576 count=1 2>/dev/null')
    assert len(metadata)==1024**2
    names=('boot','init_boot','vendor_boot','recovery','vbmeta','vbmeta_system','dtbo')
    expected={}
    for name in names:
        path='/dev/block/by-name/'+name+'_b'
        size=int(read('blockdev --getsize64 '+path))
        assert 0<size<=256*1024**2
        digest=read('sha256sum '+path).decode().split()[0]
        expected[name]=dict(bytes=size,sha256=digest,device=path)
    storage=require_build_space(out,minimum_output=sum(r['bytes'] for r in expected.values())+64*1024**2)
    out.mkdir(parents=True)
    state=dict(passed=False,scope='Current Recovery b boot-family backup only; not Android boot acceptance',
               identity=before,metadata_sha256=hashlib.sha256(metadata).hexdigest(),partitions={},
               android_boot_verified=False,root_mode_verified=False,flashed=False,slot_changed=False,
               storage_preflight=storage)
    for name,row in expected.items():
        partial=out/(name+'.img.partial')
        with partial.open('xb') as stream:
            p=subprocess.run(prefix+['exec-out','dd if='+row['device']+' bs=1048576 2>/dev/null'],
                             stdout=stream,stderr=subprocess.PIPE,timeout=120)
        p.check_returncode()
        assert partial.stat().st_size==row['bytes'] and sha(partial)==row['sha256'],name
        image=out/(name+'.img');partial.rename(image)
        state['partitions'][name]=dict(row,path=str(image))
        (out/'capture.json').write_text(json.dumps(state,indent=2)+'\n')
    assert identity()==before
    assert read('dd if=/dev/block/by-name/super bs=1048576 count=1 2>/dev/null')==metadata
    state.update(passed=True,identity_unchanged=True,metadata_unchanged=True)
    (out/'capture.json').write_text(json.dumps(state,indent=2)+'\n')
    print('current_direct_backup_complete')


if __name__=='__main__':
    main()
