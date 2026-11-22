"""Prepare external modules while retaining the selected source's load sequence."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, importlib.util, json, shutil, struct, subprocess
import argparse
from sheng_kernel_image import qualify as qualify_kernel_image
parser=argparse.ArgumentParser()
parser.add_argument('--build-root', type=Path, required=True)
parser.add_argument('--project', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args=parser.parse_args()
device=Path(__file__).resolve().parents[1]
root=args.build_root.resolve()/'k618'
project=args.project.resolve()
out=args.output.resolve()
assert not out.exists(), 'Use a new output directory'
qualification=args.build_root.resolve()/'qualified/verification.json'
qual=json.loads(qualification.read_text())
assert qual['passed']
final_image = qualify_kernel_image(root/'out-gki', Path('/root/sheng-pixelos/diagnostics/kernel618-android-deps/prebuilts/clang/host/linux-x86/clang-r584948c/bin/llvm-objcopy'))
for name in ('namespaces','dependency-graph'):
    assert json.loads((qualification.parent/(name+'.json')).read_text())['passed']
collection=json.loads((qualification.parent/'modules/collection.json').read_text())
metadata=Path(qual['modules_directory'])

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
planner = load('planner', device/'tools/plan_sheng_kernel_modules.py')
module_metadata = load('module_metadata', device/'tools/sheng_module_metadata.py')
elf = load('elf', project/'tools/audit_kernel618_modules.py')
graph = planner.ModuleGraph(*[(metadata/name).read_text() for name in
                            ('modules.dep','modules.builtin','modules.softdep')])
# Android loads each dependency row backwards; preserve depmod's ordering.
dependency_order = {}
for line in (metadata/'modules.dep').read_text().splitlines():
    owner, values = line.split(':', 1)
    dependency_order[planner.module_name(owner)] = [planner.module_name(p) for p in values.split()]
layer = project/'profiles/module-layer/lib/modules'
def read_list(name):
    return [planner.module_name(line.strip()) for line in (layer/name).read_text().splitlines()
            if line.strip() and not line.lstrip().startswith('#')]
batch = read_list('k618_batch.load')
def expanded(name):
    values = []
    for item in read_list(name):
        values.extend(batch if item == 'k618_load' else [item])
    return list(dict.fromkeys(values))
roots = dict(first_stage=expanded('modules.load'), recovery=expanded('modules.load.recovery'),
             vendor_dlkm=list(dict.fromkeys(batch)), system_dlkm=['zsmalloc', 'zram'])
# Restore the explicitly ported real providers in the vendor load sequence.
# Their hard/soft dependencies determine order through Android libmodprobe.
policy=json.loads((device/'interfaces/kernel/6.18/module-collection.json').read_text())
additional=list(policy['additional_modules'])
roots['vendor_dlkm']=list(dict.fromkeys(roots['vendor_dlkm']+additional))
for group, names in roots.items():
    missing = set(names)-set(graph.paths)-graph.builtin
    assert not missing, (group, missing)
deferred = {}
requirements = dict(roots=roots, exclusions={'k618_load':
    'Standalone embedded batch loader; expand its same real module list into standard Android init loading.'},
    test_scope='Android LTS 6.18.39 release with all restored morning hardware providers and external modules.',
    preserves_reference_module_order=True, final_product_acceptance=False)
plan = graph.plan(roots, requirements['exclusions'])
# Android libmodprobe loads hard/pre/post dependencies recursively. Preserve the
# proven root sequence instead of sorting unrelated roots alphabetically.
for group, names in roots.items():
    allowed = set(plan['install']['system_dlkm' if group == 'system_dlkm' else
                                 'vendor_dlkm' if group == 'vendor_dlkm' else 'vendor_boot'])
    plan['load'][group] = [graph.paths[name] for name in names
                           if name in graph.paths and graph.paths[name] in allowed]
out.mkdir()
(out/'requirements.json').write_text(json.dumps(requirements, indent=2)+'\n')
(out/'module-plan.json').write_text(json.dumps(plan, indent=2)+'\n')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
strip=Path('/root/sheng-pixelos/diagnostics/kernel618-android-deps/prebuilts/clang/host/linux-x86/clang-r584948c/bin/llvm-strip')
cert=root/'out-gki/certs/signing_key.x509'
key=root/'out-gki/certs/signing_key.pem'
sign=root/'out-gki/scripts/sign-file'
assert cert.read_bytes() in (root/'out-gki/certs/system_certificates.o').read_bytes(), 'Signing certificate is not embedded in this kernel'
assert key.is_file() and sign.is_file()
subprocess.run(['openssl','x509','-inform','DER','-in',str(cert),'-out',str(out/'module-signing-cert.pem')],check=True,capture_output=True)
(out/'modules').mkdir()
records={}
btf_tool=qualification.parent/'host/btf-verify'
assert btf_tool.is_file()
for name in sorted(set(graph.paths)-{'k618_load'}):
    row=collection['modules'][name]
    source=metadata/'kernel'/row['filename']
    original=elf.ElfModule(source)
    target=out/'modules'/row['filename'];data=source.read_bytes()
    # Existing signatures cover the unstripped object and must never be retained
    # after strip. The actual matching kernel key signs the packaged bytes.
    marker=b'~Module signature appended~\n'
    old_signed=data.endswith(marker)
    if old_signed:
        sigsize=struct.unpack_from('>I',data,len(data)-len(marker)-4)[0]
        data=data[:len(data)-len(marker)-12-sigsize]
    target.write_bytes(data)
    subprocess.run([str(strip),'--strip-debug',str(target)],check=True,capture_output=True)
    packed=elf.ElfModule(target)
    assert packed.versions()==original.versions() and packed.exports()==original.exports(), name
    assert packed.info==original.info and packed.get('.BTF')==original.get('.BTF'),name
    subprocess.run([str(btf_tool),'verify',str(root/'out-gki/kernel-module-base.btf'),str(target)],check=True,capture_output=True)
    subprocess.run([str(sign),'sha1',str(key),str(cert),str(target)],check=True,capture_output=True)
    signed=target.read_bytes();assert signed.endswith(marker)
    start=len(signed)-len(marker)-12
    sigsize=struct.unpack_from('>I',signed,start+8)[0]
    payload=signed[:start-sigsize];signature=signed[start-sigsize:start]
    assert payload==packed.data and signed[start+2]==2 and not any(signed[start+3:start+8]),name
    (out/'verify-module-content').write_bytes(payload);(out/'verify-module-signature').write_bytes(signature)
    subprocess.run(['openssl','cms','-verify','-binary','-inform','DER','-in',str(out/'verify-module-signature'),
        '-content',str(out/'verify-module-content'),'-certfile',str(out/'module-signing-cert.pem'),'-noverify','-out','/dev/null'],
        check=True,capture_output=True)
    records[name]=dict(filename=row['filename'],source_sha256=original.digest,packaged_sha256=sha(target),
        packaged_bytes=target.stat().st_size,btf_unchanged=True,imports_crc_unchanged=True,exports_crc_unchanged=True,
        signature_verified=True,prior_object_was_signed=old_signed)
    del original,packed

def install_modules(base,installed,loaded):
    base.mkdir(parents=True)
    names={planner.module_name(p) for p in installed}
    for name in names:
        shutil.copyfile(out/'modules'/records[name]['filename'],base/records[name]['filename'])
    lines=[]
    for name in sorted(names):
        dependencies=dependency_order[name]
        assert set(dependencies)==graph.hard[name]
        assert set(dependencies)<=names,(base,name,set(dependencies)-names)
        lines.append(module_metadata.format_dependency(records[name]['filename'], [records[d]['filename'] for d in dependencies]))
    (base/'modules.dep').write_text('\n'.join(lines)+'\n')
    aliases=[]
    for line in (metadata/'modules.alias').read_text().splitlines():
        if line.startswith('#') or (line.split() and planner.module_name(line.split()[-1]) in names): aliases.append(line)
    (base/'modules.alias').write_text('\n'.join(aliases)+'\n')
    softdeps=[]
    for line in (metadata/'modules.softdep').read_text().splitlines():
        if line.startswith('#') or (line.split() and planner.module_name(line.split()[1]) in names):softdeps.append(line)
    (base/'modules.softdep').write_text('\n'.join(softdeps)+'\n')
    (base/'modules.load').write_text('\n'.join(records[planner.module_name(p)]['filename'] for p in loaded)+'\n')
    (base/'modules.builtin').write_text((metadata/'modules.builtin').read_text())
    (base/'modules.builtin.modinfo').write_bytes((metadata/'modules.builtin.modinfo').read_bytes())
    for p in base.iterdir():p.chmod(0o644)

install_modules(out/'vendor_dlkm/lib/modules',plan['install']['vendor_dlkm'],plan['load']['vendor_dlkm'])
install_modules(out/'system_dlkm/lib/modules/android17-6.18',plan['install']['system_dlkm'],plan['load']['system_dlkm'])
install_modules(out/'vendor_ramdisk/lib/modules',plan['install']['vendor_boot'],plan['load']['first_stage'])
boot_modules=out/'vendor_ramdisk/lib/modules'
(boot_modules/'modules.load.recovery').write_text('\n'.join(records[planner.module_name(p)]['filename'] for p in plan['load']['recovery'])+'\n')
report=dict(updated_utc=datetime.now(timezone.utc).isoformat(),candidate=str(out),qualification=str(qualification),
    final_kernel_image=final_image,
    final_kernel_out=str((root/'out-gki').resolve()),
    module_count=len(records),module_signing_certificate_sha256=sha(cert),modules=records,
    kernel_image_sha256=sha(root/'out-gki/kernel-Image'),kernel_release=collection['kernel_release'],
    staged_partitions=['vendor_dlkm','system_dlkm','vendor_ramdisk'],
    deferred_legacy_names=sorted(deferred),user_requested_optional_interface_deferral=False,
    final_product_acceptance=False,flashed=False,boot_verified=False)
(out/'prepared.json').write_text(json.dumps(report,indent=2)+'\n')

print(json.dumps(dict(candidate=str(out),modules=len(records),signature_and_btf_verified=True,
    boot_modules=len(plan['install']['vendor_boot']),deferred_legacy_interfaces=len(deferred))))

# Only fresh, qualified artifacts from this build are passed to the ROM tools.
lines=[
    'TARGET_FORCE_PREBUILT_KERNEL := true',
    'TARGET_PREBUILT_KERNEL := '+str(root/'out-gki/kernel-Image'),
    'TARGET_KERNEL_EXT_MODULES :=',
    'BOOT_KERNEL_MODULES :=',
    'RECOVERY_KERNEL_MODULES :=',
    'SYSTEM_KERNEL_MODULES :=',
    'BOARD_KERNEL_CMDLINE += sched_proxy_exec=0',
    'BOARD_DO_NOT_STRIP_VENDOR_MODULES := true',
    'BOARD_DO_NOT_STRIP_VENDOR_RAMDISK_MODULES := true',
    'BOARD_DO_NOT_STRIP_RECOVERY_MODULES := true',
]
for key,install,load in (
    ('VENDOR','vendor_dlkm','vendor_dlkm'),
    ('SYSTEM','system_dlkm','system_dlkm'),
    ('VENDOR_RAMDISK','vendor_boot','first_stage'),
    ('RECOVERY','vendor_boot','recovery'),
):
    paths=[str(out/'modules'/records[planner.module_name(p)]['filename']) for p in plan['install'][install]]
    names=[records[planner.module_name(p)]['filename'] for p in plan['load'][load]]
    lines += ['BOARD_'+key+'_KERNEL_MODULES := '+' '.join(paths),
              'BOARD_'+key+'_KERNEL_MODULES_LOAD := '+' '.join(names)]
lines += ['BOARD_VENDOR_RAMDISK_RECOVERY_KERNEL_MODULES_LOAD := '+
          ' '.join(records[planner.module_name(p)]['filename'] for p in plan['load']['recovery'])]
(out/'BoardConfigSourceKernel.mk').write_text('\n'.join(lines)+'\n')
