#!/usr/bin/env python3
"""Install the sealed pen UI update on ca10ede3 A and verify all fourteen partitions."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--flash',action='store_true')
    parser.add_argument('--package',type=Path)
    parser.add_argument('--installed-package',type=Path,help='Exact sealed r66 manifest already installed; otherwise verify r65')
    args=parser.parse_args()
    workspace=Path(__file__).resolve().parents[4]
    out=Path(tempfile.mkdtemp(prefix='flash-r66-',dir=workspace/'reports/device/20261114-stylus-service'))
    adb=workspace/'tools/platform-tools/adb.exe';fastboot=workspace/'tools/platform-tools/fastboot.exe'
    package_path=args.package.resolve() if args.package else workspace/'artifacts/system-hardware-followup-sheng-r66/build-result.json'
    package=json.loads(package_path.read_text())
    ime_update=package.get('kind')=='targeted-handwriting-ime-preinstall'
    if ime_update:
        relative=Path(package['baseline_manifest'])
        assert not relative.is_absolute() and '..' not in relative.parts
        baseline_path=workspace/relative
    else:baseline_path=workspace/'artifacts/system-hardware-followup-sheng-r65/build-result.json'
    baseline=json.loads(baseline_path.read_text())
    image_partition='product' if ime_update else 'system_ext'
    changed_partitions={image_partition,'vbmeta_system'}
    receipt=dict(started_utc=datetime.now(timezone.utc).isoformat(),serial='ca10ede3',slot='a',revision=66,
                 completed=False,flashed_partitions=[],postboot_partitions_verified=[],commands=[])
    def save(): (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    def call(tool,*arguments,timeout=60):
        result=subprocess.run([str(tool),'-s','ca10ede3',*map(str,arguments)],capture_output=True,timeout=timeout)
        text=(result.stdout+result.stderr).decode(errors='replace')
        receipt['commands'].append(dict(tool=Path(tool).name,args=list(map(str,arguments)),returncode=result.returncode,output=text));save()
        if result.returncode:raise RuntimeError(text)
        return text.strip()
    def shell(command):return call(adb,'shell',command)
    def identity(restore=False):
        expected={'ro.product.device':'sheng','ro.boot.slot_suffix':'_a','sys.boot_completed':'1','ro.boot.flash.locked':'0'}
        for name,value in expected.items():assert shell('getprop '+name)==value,name
        uid=shell('id -u')
        if uid=='2000' and restore and not receipt.get('debug_root_restored'):
            call(adb,'root');receipt['debug_root_restored']=True;raise RuntimeError('Reconnecting adbd after debug root')
        assert uid=='0' and shell('getenforce')=='Enforcing'
        assert shell('uname -r')=='5.15.220-gf9ca2b71f672'
    logical={'system','system_ext','product','vendor','odm','system_dlkm','vendor_dlkm'}
    allowed=logical|{'boot','init_boot','vendor_boot','recovery','dtbo','vbmeta','vbmeta_system'}
    def partition(entry):
        name=entry['partition'];assert name in allowed
        assert re.fullmatch('[0-9a-f]{64}',entry['sha256']) and entry['bytes']>0
        command=('sha256sum /dev/block/mapper/'+name+'_a') if name in logical else (
            'head -c '+str(entry['bytes'])+' /dev/block/by-name/'+name+'_a | sha256sum')
        assert shell(command).split()[0]==entry['sha256'],name
    def wait(check,seconds):
        deadline=time.monotonic()+seconds;last=None
        while time.monotonic()<deadline:
            try:check();return
            except (Exception,AssertionError) as error:last=error
            time.sleep(2)
        raise RuntimeError('Device transition timed out: '+str(last))
    def fastboot_state(userspace):
        for name,value in [('product','sheng'),('current-slot','a'),('is-userspace','yes' if userspace else 'no')]:
            output=call(fastboot,'getvar',name,timeout=10)
            assert re.search(r'(?m)^'+name+r':\s*'+value+r'\s*$',output),output
    try:
        assert package['revision']==66 and package['baseline_revision']==(66 if ime_update else 65)
        assert sha(baseline_path)==package['baseline_manifest_sha256']
        for key in ('complete_avb_chain_verified','policy_and_vintf_inputs_unchanged','native_service_unchanged',
                    'systemui_unchanged','native_c_staging'):assert package[key] is True,key
        assert package['e_drive_swap_allowed'] is False and package['normal_module_build_passed'] is False
        assert set(package['entries'])=={image_partition}
        if ime_update:
            assert args.installed_package is None
            assert baseline['revision']==66 and baseline['baseline_revision']==65
            assert baseline['complete_avb_chain_verified'] and baseline['native_service_unchanged']
            for key in ('prebuilt_ime_qualified','partition_sizes_unchanged','ime_original_signature_preserved'):
                assert package[key] is True,key
            expected_entries={'app/ShengSogouIme/ShengSogouIme.apk'}
            metadata=json.loads((workspace/'device/xiaomi/sheng/interfaces/input/ime/source.json').read_text())
            assert package['entries']['product']['app/ShengSogouIme/ShengSogouIme.apk']['sha256']==metadata['sha256']
            assert package['ime_certificate_sha256']==metadata['certificate_sha256']
        else:
            assert package['targeted_ui_build_passed'] is True
            expected_entries={'app/ShengPenSettings/ShengPenSettings.apk','priv-app/ShengStylus/ShengStylus.apk'}
            if package.get('preinstalled_ime_included'):
                assert package['ime_original_signature_preserved'] is True
                expected_entries.add('app/ShengSogouIme/ShengSogouIme.apk')
        if 'product_registration_sha256' in package:
            assert sha(workspace/'device/xiaomi/sheng/device.mk')==package['product_registration_sha256']
        assert set(package['entries'][image_partition])==expected_entries
        assert package['partition_reports'][image_partition]['metadata_preserved']
        assert {row['partition'] for row in package['files']}==changed_partitions
        old=baseline['files']+baseline['unchanged_partition_files']
        assert len(old)==14 and {row['partition'] for row in old}==allowed
        assert package['baseline_partitions']==old
        expected_retained=[row for row in old if row['partition'] not in changed_partitions]
        assert package['unchanged_partition_files']==expected_retained
        live=old
        if args.installed_package:
            installed_path=args.installed_package.resolve()
            installed=json.loads(installed_path.read_text())
            assert installed['revision']==66 and installed['baseline_revision']==65
            assert installed['baseline_manifest_sha256']==sha(baseline_path)
            assert installed['complete_avb_chain_verified'] and installed['native_service_unchanged']
            assert installed['unchanged_partition_files']==expected_retained
            assert {row['partition'] for row in installed['files']}=={'system_ext','vbmeta_system'}
            live=installed['files']+installed['unchanged_partition_files']
            assert len(live)==14
            receipt['installed_manifest_sha256']=sha(installed_path)
        if not ime_update:
            build_path=workspace/package['build_receipt'];assert sha(build_path)==package['build_receipt_sha256']
            build=json.loads(build_path.read_text());assert build['passed']
            if package.get('targeted_controls_build_passed'):
                assert build.get('controls_regression_passed') is True
                assert package['controls_validation_sha256']==build['controls_validation_sha256']
        for relative,digest in package['source_sha256'].items():assert sha(workspace/'device/xiaomi/sheng'/relative)==digest,relative
        images={}
        for row in package['files']:
            path=package_path.parent/row['name']
            assert path.stat().st_size==row['bytes'] and sha(path)==row['sha256']
            images[row['partition']]=subprocess.check_output(['wslpath','-w',str(path)],text=True).strip()
        receipt['manifest_sha256']=sha(package_path);receipt['package_verified']=True
        identity()
        for row in live:partition(row)
        receipt['live_baseline_verified']=True
        receipt['live_baseline_revision']=66 if args.installed_package or ime_update else 65
        receipt['live_r65_baseline_verified']=not bool(args.installed_package or ime_update);save()
        print('Installed baseline and declared pen APK update verified.',flush=True)
        if args.flash:
            # Android caches parsed manifests by their directory identity.
            # Preserve the exact two regenerable entries before expiring them.
            for name in (('ShengSogouIme',) if ime_update else ('ShengPenSettings','ShengStylus')):
                paths=shell('find /data/system/package_cache -mindepth 2 -maxdepth 2 -type f -name "'+name+'-*" -print').splitlines()
                for remote in paths:
                    assert re.fullmatch(r'/data/system/package_cache/[0-9a-f]{40}/'+name+r'-[0-9]+--?[0-9]+',remote),remote
                    blob=subprocess.check_output([str(adb),'-s','ca10ede3','exec-out','cat',remote])
                    (out/(name+'-'+Path(remote).parent.name+'.cache')).write_bytes(blob)
                    shell('rm -- '+remote)
            call(adb,'reboot','fastboot');wait(lambda:fastboot_state(True),120)
            print(call(fastboot,'flash',image_partition+'_a',images[image_partition],timeout=300),flush=True)
            receipt['flashed_partitions'].append(image_partition);save()
            call(fastboot,'reboot','bootloader');wait(lambda:fastboot_state(False),120)
            assert re.search(r'(?m)^unlocked:\s*yes\s*$',call(fastboot,'getvar','unlocked'))
            print(call(fastboot,'flash','vbmeta_system_a',images['vbmeta_system']),flush=True)
            receipt['flashed_partitions'].append('vbmeta_system');save()
            call(fastboot,'reboot');wait(lambda:identity(True),240)
            for row in package['files']+package['unchanged_partition_files']:
                partition(row);receipt['postboot_partitions_verified'].append(row['partition']);save()
            assert set(receipt['postboot_partitions_verified'])==allowed
            print('r66 booted Enforcing; all fourteen partition readbacks match.',flush=True)
        receipt['completed']=True
    except BaseException as error:receipt['error']=repr(error);raise
    finally:
        receipt['finished_utc']=datetime.now(timezone.utc).isoformat();save();print(out,flush=True)

if __name__=='__main__':main()
