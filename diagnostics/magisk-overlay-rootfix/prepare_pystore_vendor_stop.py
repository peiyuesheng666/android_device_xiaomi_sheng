#!/usr/bin/env python3
"""Generate only the device-owned boot-stop RC/CIL delta and compile full policy.

Never disables neverallow checks. This prepares an offline payload, not an image
or deployment. All other extracted vendor files remain untouched.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
from export_source_built_binaries import sha


def source_delta(device, version):
    label='vendor_sysfs_sheng_boot_complete'
    node='/module/sheng_bootlog/parameters/boot_complete'
    expected={
        'sepolicy/vendor/file.te':f'type {label}, fs_type, sysfs_type;',
        'sepolicy/vendor/vendor_init.te':f'allow vendor_init {label}:file {{ open write getattr }};',
        'sepolicy/vendor/genfs_contexts':f'genfscon sysfs {node} u:object_r:{label}:s0',
    }
    for rel,line in expected.items():
        assert (device/rel).read_text().splitlines().count(line)==1,rel
    rc=(device/'rootdir/etc/init.sheng.rc').read_text()
    block='on property:sys.boot_completed=1\n    write /sys'+node+' 1\n'
    assert rc.count(block)==1
    assert re.fullmatch(r'[0-9]{6}',version)
    cil=(f'(type {label})\n'
         f'(roletype object_r {label})\n'
         f'(typeattributeset fs_type ({label}))\n'
         f'(typeattributeset sysfs_type ({label}))\n'
         f'(allow vendor_init_{version} {label} (file (getattr open write)))\n'
         f'(genfscon sysfs "{node}" (u object_r {label} ((s0) (s0))))\n')
    return block,cil,expected


def policy_inputs(inputs, vendor, version):
    files=[inputs/'system/selinux/plat_sepolicy.cil',
           inputs/('system/selinux/mapping/'+version+'.cil')]
    assert all(p.is_file() for p in files)
    for name,rel in [('system','mapping/'+version+'.compat.cil'),
                     ('system_ext','system_ext_sepolicy.cil'),
                     ('system_ext','mapping/'+version+'.cil'),
                     ('system_ext','mapping/'+version+'.compat.cil'),
                     ('product','product_sepolicy.cil'),('product','mapping/'+version+'.cil')]:
        p=inputs/name/'selinux'/rel
        if p.is_file():
            files.append(p)
    files.extend([vendor/'plat_pub_versioned.cil',vendor/'vendor_sepolicy.cil'])
    odm=inputs/'odm/odm_sepolicy.cil'
    if odm.is_file():
        files.append(odm)
    genfs=inputs/'system/selinux'/('plat_sepolicy_genfs_'+version+'.cil')
    assert genfs.is_file()
    files.append(genfs)
    return files


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('device','vendor-root','policy-inputs','secilc','out'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    out=args.out.resolve()
    assert not out.exists()
    vendor=args.vendor_root/'etc/selinux'
    version=(vendor/'plat_sepolicy_vers.txt').read_text().strip()
    assert (vendor/'genfs_labels_version.txt').read_text().strip()==version
    block,delta,sources=source_delta(args.device,version)
    original_rc=args.vendor_root/'etc/init/init.sheng.rc'
    original_cil=vendor/'vendor_sepolicy.cil'
    assert 'sheng_bootlog/parameters/boot_complete' not in original_rc.read_text()
    assert 'vendor_sysfs_sheng_boot_complete' not in original_cil.read_text()
    out.mkdir(parents=True)
    rc=out/'payload/etc/init/init.sheng.rc'
    cil=out/'payload/etc/selinux/vendor_sepolicy.cil'
    rc.parent.mkdir(parents=True);cil.parent.mkdir(parents=True)
    rc.write_text(original_rc.read_text().rstrip()+'\n\n'+block)
    cil.write_text(original_cil.read_text().rstrip()+'\n'+delta)
    (out/'rule-delta.cil').write_text(delta)
    files=policy_inputs(args.policy_inputs,vendor,version)
    inputs={str(p):sha(p) for p in files}
    commands=[]
    for label,replacement in [('baseline',original_cil),('pystore',cil)]:
        selected=[replacement if p==original_cil else p for p in files]
        # PolicyVers=30 in the current source's system/sepolicy/build/soong/policy.go.
        # Runtime init uses -N, but this offline gate deliberately keeps neverallow.
        cmd=[str(args.secilc.resolve(strict=True)),str(selected[0]),'-m','-M','true','-G',
             '-c','30','-o',str(out/(label+'.policy')),'-f',str(out/(label+'.contexts'))]
        cmd.extend(map(str,selected[1:]))
        p=subprocess.run(cmd,capture_output=True,timeout=180)
        (out/(label+'.stdout')).write_bytes(p.stdout)
        (out/(label+'.stderr')).write_bytes(p.stderr)
        commands.append(dict(label=label,argv=cmd,returncode=p.returncode))
        (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        p.check_returncode()
    assert inputs=={str(p):sha(p) for p in files}
    q=dict(passed=True,scope='offline source-derived vendor boot-stop RC/CIL payload and full policy compile',
           neverallow_checks_enabled=True,platform_policy_version=version,
           original_vendor_rc_sha256=sha(original_rc),original_vendor_cil_sha256=sha(original_cil),
           source_sha256={rel:sha(args.device/rel) for rel in list(sources)+['rootdir/etc/init.sheng.rc']},
           compiled_input_sha256=inputs,compiler_sha256=sha(args.secilc),
           payload={'/etc/init/init.sheng.rc':dict(path=str(rc),sha256=sha(rc)),
                    '/etc/selinux/vendor_sepolicy.cil':dict(path=str(cil),sha256=sha(cil))},
           compiled_policy_sha256=sha(out/'pystore.policy'),
           images_packaged=False,runtime_verified=False,flashed=False)
    (out/'qualification.json').write_text(json.dumps(q,indent=2)+'\n')
    print(json.dumps(q,indent=2))


if __name__=='__main__':
    main()
