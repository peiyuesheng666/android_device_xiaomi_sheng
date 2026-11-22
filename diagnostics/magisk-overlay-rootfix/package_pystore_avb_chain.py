#!/usr/bin/env python3
"""Sign/verify matched pystore AVB against pinned baseline and captured physical companions.
No device access; this does not prove snapshot-composed runtime or deployment.
"""
from pathlib import Path
import argparse, importlib.util, json, os, shutil, subprocess, sys, tempfile, hashlib
from qualify_captured_avb_chain import public_key, replace_descriptors, verification_commands, mark_unqualified
from storage_guard import require_build_space
from package_remounter_trial import sha
parser=argparse.ArgumentParser(description=__doc__)
for name in ('family','vendor-dlkm','system-dlkm','companions','baseline','baseline-manifest','out','rom','host-tools'):
    parser.add_argument('--'+name,type=Path,required=True)
parser.add_argument('--root-mode',choices=('Magisk','KernelSU'),default='Magisk')
parser.add_argument('--current-init-backup',type=Path)
parser.add_argument('--ksu-module-audit',type=Path)
parser.add_argument('--kernel-input-audit',type=Path)
args=parser.parse_args()
out=args.out.resolve()
scratch=out/'work'
assert not out.exists()
rom=args.rom.resolve(strict=True)
bootq=json.loads((args.family/'qualification.json').read_text())
vendorq=json.loads((args.vendor_dlkm/'qualification.json').read_text())
systemq=json.loads((args.system_dlkm/'qualification.json').read_text())
physical=json.loads((args.companions/'capture.json').read_text())
assert physical['passed'] and physical['physical_backing_only']
assert physical['identity'][:5]==['ca10ede3','sheng','_b','running','0']
assert physical['metadata_unchanged'] and physical['identity_unchanged']
assert all(q['passed'] and not q['flashed'] for q in (bootq,vendorq,systemq))
assert bootq['release_pystore'] or bootq['preserve_rawdump_cmdlines_requested_in_boot_and_recovery']
assert bootq['module_stage_receipt_sha256']==vendorq['module_stage_receipt_sha256']==systemq['module_stage_receipt_sha256']
rows=dict(physical['partitions'])
for name,row in bootq['images'].items():
    rows[name]={key:row[key] for key in ('path','sha256','bytes')}
for name,q in (('vendor_dlkm',vendorq),('system_dlkm',systemq)):
    rows[name]=dict(path=q['image'],sha256=q['sha256'],bytes=q['bytes'])
known=json.loads(args.baseline_manifest.read_text())
root_init=known['modes'][args.root_mode]['init_boot']
init_provenance='pinned historical init_boot'
if args.current_init_backup:
    assert args.root_mode=='KernelSU' and args.ksu_module_audit and args.kernel_input_audit
    backup=json.loads(args.current_init_backup.read_text())
    assert backup['passed'] and backup['identity']==physical['identity']
    assert backup['metadata_sha256']==physical['metadata_sha256']
    root_init=backup['partitions']['init_boot']
    parent_init=Path(root_init['path'])
    assert sha(parent_init)==root_init['sha256']
    ka=json.loads(args.kernel_input_audit.read_text())
    assert ka['passed'] and sha(args.kernel_input_audit)==bootq['kernel_audit_sha256']
    ksu=json.loads(args.ksu_module_audit.read_text())
    assert ksu['passed'] and all(ksu[k] is True for k in
        ('exported_reference_crcs_match','namespace_imports_match','runtime_symbol_names_resolve_uniquely'))
    assert ksu['vmlinux_sha256']==ka['final_kernel_image']['inputs_sha256']['vmlinux']
    assert ksu['symvers_sha256']==ka['final_kernel_image']['inputs_sha256']['Module.symvers']
    from package_source_boot_family import inventory
    with tempfile.TemporaryDirectory(prefix='sheng-ksu-init-inspect-') as temporary:
        subprocess.run([sys.executable,str(rom/'system/tools/mkbootimg/unpack_bootimg.py'),
                        '--boot_img',str(parent_init),'--out',temporary],
                       check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45)
        entries=inventory(subprocess.check_output(['lz4','-dc',str(Path(temporary)/'ramdisk')],timeout=45))
        assert {'init','init.real','kernelsu.ko'}<=set(entries) and '.backup/init.xz' not in entries
        assert hashlib.sha256(entries['kernelsu.ko']['payload']).hexdigest()==ksu['module_sha256']
    init_provenance='preserved current KSU init_boot; embedded module bound to new kernel audit'
else:
    assert not args.ksu_module_audit and not args.kernel_input_audit
    assert sha(args.baseline/root_init['path'])==root_init['sha256']
assert bootq['images']['init_boot']['sha256']==root_init['sha256']
direct=json.loads((args.companions/'live-direct.json').read_text())
direct_context=json.loads((args.companions/'live-direct-context.json').read_text())
assert direct_context['passed'] and direct_context['identity']==physical['identity']
assert direct_context['metadata_sha256']==physical['metadata_sha256']
for name in ('dtbo','vbmeta_system','vbmeta'):
    rows[name]=direct[name]
assert set(rows)=={'boot','vendor_boot','init_boot','recovery','vendor_dlkm','system_dlkm','system','system_ext','product','vendor','odm','dtbo','vbmeta','vbmeta_system'}
storage=require_build_space(out,minimum_output=512*1024**2,minimum_host=2*1024**3)
capture=False
out.mkdir()
scratch.mkdir()
mark_unqualified(out)
logs = out/'logs'; logs.mkdir()
images = scratch/'images'; images.mkdir()
state = dict(status='input-hashing', passed=False, flashed=False, runtime_verified=False,
             deployable_combination=False, device_access=False, commands=[])

def save():
    (out/'state.json').write_text(json.dumps(state, indent=2)+'\n')

save()
for name, row in rows.items():
    path = Path(row['path'])
    assert path.stat().st_size == row['bytes'] and sha(path) == row['sha256'], name
    if name != 'vbmeta':
        (images/(name+'.img')).symlink_to(path)
state['status'] = 'signing'; save()
avbpath = rom/'external/avb/avbtool.py'
spec = importlib.util.spec_from_file_location('diagnostic_avb', avbpath)
avb = importlib.util.module_from_spec(spec); spec.loader.exec_module(avb)

def info(path):
    handler = avb.ImageHandler(str(path), read_only=True)
    try:
        return avb.Avb()._parse_image(handler)
    finally:
        handler._image.close()

root = Path(rows['vbmeta']['path'])
_, rh, rd, _ = info(root)
assert rh.flags == 1 and rh.algorithm_type == 2 and rh.public_key_metadata_size == 0
assert avb.verify_vbmeta_signature(rh, root.read_bytes())
types = (avb.AvbHashDescriptor, avb.AvbHashtreeDescriptor)
old = {d.partition_name: d for d in rd if isinstance(d, types)}
assert len(old) == sum(isinstance(d, types) for d in rd)
assert set(old) == {'boot','dtbo','init_boot','recovery','vendor_boot','odm','system_dlkm','vendor','vendor_dlkm'}
replacements = {}
for name in ('boot','vendor_boot','init_boot','recovery','vendor_dlkm','system_dlkm'):
    _, header, descriptors, _ = info(images/(name+'.img'))
    candidates = [d for d in descriptors if isinstance(d, types)]
    assert header.algorithm_type == 0 and header.flags == 0 and len(candidates) == 1
    d = candidates[0]
    assert d.partition_name == name and type(d) is type(old[name])
    assert d.flags == old[name].flags == 0
    assert d.salt == old[name].salt and d.hash_algorithm == old[name].hash_algorithm
    if isinstance(d, avb.AvbHashtreeDescriptor):
        for field in ('dm_verity_version','data_block_size','hash_block_size','fec_num_roots'):
            assert getattr(d, field) == getattr(old[name], field)
    replacements[name] = d
new_descriptors = replace_descriptors(rd, replacements, types)
rootkey = rom/'external/avb/test/data/testkey_rsa4096.pem'
childkey = rom/'external/avb/test/data/testkey_rsa2048.pem'
with avb.load_public_key(str(rootkey)) as key:
    assert key.encode() == public_key(root, rh)
blob = avb.Avb()._generate_vbmeta_blob(
    algorithm_name='SHA256_RSA4096', key_path=str(rootkey), public_key_metadata_path=None,
    descriptors=new_descriptors, chain_partitions_use_ab=None, chain_partitions_do_not_use_ab=None,
    rollback_index=rh.rollback_index, flags=rh.flags, rollback_index_location=rh.rollback_index_location,
    props=None, props_from_file=None, kernel_cmdlines=None, setup_rootfs_from_kernel=None,
    ht_desc_to_setup=None, include_descriptors_from_image=None, signing_helper=None,
    signing_helper_with_files=None, release_string=rh.release_string,
    append_to_release_string=None, required_libavb_version_minor=rh.required_libavb_version_minor)
assert len(blob) <= rows['vbmeta']['bytes']
candidate = out/'vbmeta.img'
candidate.write_bytes(blob+b'\0'*(rows['vbmeta']['bytes']-len(blob)))
(images/'vbmeta.img').symlink_to(candidate)
_, nh, nd, _ = info(candidate)
assert vars(nh) == vars(rh) and public_key(candidate, nh) == public_key(root, rh)
assert avb.verify_vbmeta_signature(nh, candidate.read_bytes())
assert [d.encode() for d in nd] == [d.encode() for d in new_descriptors]
assert [d.encode() for d in nd if not isinstance(d, types)] == [d.encode() for d in rd if not isinstance(d, types)]
chains = [d for d in nd if isinstance(d, avb.AvbChainPartitionDescriptor)]
assert len(chains) == 1 and chains[0].partition_name == 'vbmeta_system'
chain = chains[0]
child = images/'vbmeta_system.img'
_, ch, _, _ = info(child)
assert ch.flags == 0 and avb.verify_vbmeta_signature(ch, child.read_bytes())
assert chain.rollback_index_location == 1 and chain.public_key == public_key(child, ch)
with avb.load_public_key(str(childkey)) as key:
    assert key.encode() == chain.public_key
chainkey = out/'expected-child.avbpubkey'; chainkey.write_bytes(chain.public_key)
env = dict(os.environ, PATH=str(args.host_tools.resolve())+':'+os.environ['PATH'])

def run(cmd, label, expected=True):
    state['status'] = label; save()
    p = subprocess.run(list(map(str, cmd)), capture_output=True, timeout=1200, env=env)
    (logs/(label+'.stdout')).write_bytes(p.stdout)
    (logs/(label+'.stderr')).write_bytes(p.stderr)
    state['commands'].append(dict(label=label, argv=list(map(str, cmd)), returncode=p.returncode))
    save()
    assert (p.returncode == 0) == expected, label

cmds = verification_commands(avbpath, images, rootkey, childkey, chainkey, chain.rollback_index_location)
for i, cmd in enumerate(cmds):
    run(cmd, 'full-chain-level-'+str(i))
# Negative tests operate on PRIVATE copies, never source symlink targets.
negative = scratch/'negative'; negative.mkdir()
for p in images.iterdir():
    if p.name != 'boot.img':
        (negative/p.name).symlink_to(p)
testboot = negative/'boot.img'
shutil.copyfile(images/'boot.img', testboot)
with testboot.open('r+b') as f:
    f.seek(4096); original = f.read(1); assert len(original) == 1
    f.seek(4096); f.write(bytes([original[0]^1]))
negative_cmd = verification_commands(avbpath, negative, rootkey, childkey, chainkey, chain.rollback_index_location)[0]
run(negative_cmd, 'negative-corrupted-boot', False)
# Check that this negative really failed on payload verification.
negative_error = (logs/'negative-corrupted-boot.stderr').read_text(errors='replace')
negative_output = (logs/'negative-corrupted-boot.stdout').read_text(errors='replace')
assert 'boot' in negative_error+negative_output and ('digest' in (negative_error+negative_output).lower() or 'hash' in (negative_error+negative_output).lower())
with testboot.open('r+b') as f:
    f.seek(4096); f.write(original)
assert sha(testboot) == rows['boot']['sha256']
run(negative_cmd, 'negative-private-copy-restored')
tampered = out/'negative-signature.img'; shutil.copyfile(candidate, tampered)
with tampered.open('r+b') as f:
    offset = nh.SIZE+nh.signature_offset
    f.seek(offset); byte=f.read(1); assert len(byte)==1
    f.seek(offset); f.write(bytes([byte[0]^1]))
run([sys.executable,avbpath,'verify_image','--image',tampered,'--key',rootkey], 'negative-root-signature', False)
run([sys.executable,avbpath,'verify_image','--image',candidate,'--key',childkey], 'negative-wrong-root-key', False)
for name, row in rows.items():
    assert sha(Path(row['path'])) == row['sha256'], (name, 'protected input changed')
changes = [name for name, d in old.items() if d.encode() != next(n for n in nd if isinstance(n, types) and n.partition_name == name).encode()]
assert set(changes) - {'init_boot'} == {'boot','vendor_boot','recovery','vendor_dlkm','system_dlkm'}
records = dict(rows)
records['vbmeta'] = dict(path=str(candidate),sha256=sha(candidate),bytes=candidate.stat().st_size)
q = dict(passed=True, scope='offline exact pystore family with captured physical companions',
    root_mode=args.root_mode, init_provenance=init_provenance,
    ksu_module_audit_sha256=sha(args.ksu_module_audit) if args.ksu_module_audit else None,
    historical_baseline_manifest_sha256=sha(args.baseline_manifest),
    physical_backing_only=True, snapshot_composed_runtime_verified=False,
    physical_capture_boot_id=physical['identity'][-1],
    full_offline_avb_chain_verified=True, root_flags=nh.flags, verification_disabled=False,
    root_public_key_preserved=True, child_chain_key_verified=True,
    current_child_sha256=sha(child), input_inventory=records,
    changed_root_descriptors=changes, negative_corrupted_payload_rejected=True,
    negative_bad_signature_rejected=True, negative_wrong_root_key_rejected=True,
    private_payload_restoration_verified=True, original_inputs_unchanged=True,
    prepared_sha256=bootq['module_stage_receipt_sha256'], storage_preflight=storage,
    candidate_sha256=sha(candidate), full_chain_levels_verified=2,
    logical_partition_current_capacity_verified=False,
    rawdump_preservation_runtime_verified=False, bounded_return_runtime_verified=False,
    capture_mode=capture,
    flashed=False, runtime_verified=False, deployable_combination=False, device_access=False)
(out/'qualification.json').write_text(json.dumps(q, indent=2)+'\n')
state.update(status='complete',passed=True); save()
print(json.dumps({k:v for k,v in q.items() if k!='input_inventory'},indent=2),flush=True)
