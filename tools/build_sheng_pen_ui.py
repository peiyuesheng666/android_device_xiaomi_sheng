#!/usr/bin/env python3
"""Build only the two device-owned pen APKs over the installed r65 native service."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preaudit',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--controls-validation',type=Path,
                        help='Successful current-source button checks; permits the reviewed GATT extension')
    parser.add_argument('--include-ime',action='store_true',
                        help='Also qualify the separately signed OEM handwriting IME for preinstallation')
    args=parser.parse_args()
    workspace=Path(__file__).resolve().parents[4]
    device=workspace/'device/xiaomi/sheng'
    source=device/'interfaces/input/stylus'
    pen=device/'interfaces/input/pen'
    ime=device/'interfaces/input/ime'
    rom=Path('/root/sheng-lineage/lineage-24.0')
    host=rom/'out/host/linux-x86/bin'; jdk=rom/'prebuilts/jdk/jdk21/linux-x86/bin'
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    native=Path(tempfile.mkdtemp(prefix='pen-ui-',dir=rom.parent/'hardware-diagnostics'))
    product=out/'product'; product.mkdir()
    baseline_path=workspace/'artifacts/system-hardware-followup-sheng-r65/build-result.json'
    baseline=json.loads(baseline_path.read_text())
    roots=(source,pen,ime) if args.include_ime else (source,pen)
    snapshot=lambda: {str(path.relative_to(device)):sha(path) for root in roots
                      for path in sorted(root.rglob('*')) if path.is_file()}
    before=snapshot()
    allowed={'interfaces/input/stylus/Android.bp','interfaces/input/stylus/AndroidManifest.xml',
             'interfaces/input/stylus/app/org/lineageos/sheng/stylus/ShengStylusApplication.java'}
    validation=None
    if args.controls_validation:
        validation=json.loads(args.controls_validation.read_text())
        assert validation['passed'] and validation['assertions'] >= 40
        for relative,digest in validation['source_sha256'].items():assert sha(device/relative)==digest,relative
        allowed.add('interfaces/input/stylus/app/org/lineageos/sheng/stylus/PenGattSession.java')
    for relative,digest in baseline['sources_sha256'].items():
        if relative not in allowed: assert sha(device/relative)==digest,relative
    receipt=dict(date_utc=datetime.now(timezone.utc).isoformat(),kind='targeted-pen-ui-apks',passed=False,
                 normal_module_build_passed=False,full_product_build_passed=False,ninja_graph_loaded=False,
                 native_service_unchanged=True,policy_unchanged=True,source_sha256=before,
                 preinstalled_ime_included=args.include_ime,
                 baseline_manifest_sha256=sha(baseline_path),product_root=str(product),work_dir=str(native),commands=[])
    if validation:
        receipt.update(kind='targeted-pen-controls-apks',controls_regression_passed=True,
                       controls_validation_sha256=sha(args.controls_validation),
                       controls_validation=str(args.controls_validation))
    if args.include_ime:
        receipt.update(kind='targeted-pen-controls-and-ime-apks' if validation else 'targeted-pen-ui-and-ime-apks',
                       product_registration_sha256=sha(device/'device.mk'))
    def save(): (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    def run(argv,label):
        argv=list(map(str,argv));env=dict(os.environ,LANG='C.UTF-8',LC_ALL='C.UTF-8')
        if Path(argv[0]).name not in ('java','javac'):env['LD_LIBRARY_PATH']=str(host.parent/'lib64')
        else:env.pop('LD_LIBRARY_PATH',None)
        result=subprocess.run(argv,env=env,capture_output=True,text=True,timeout=300)
        (out/(label+'.log')).write_text(result.stdout+result.stderr)
        receipt['commands'].append(dict(argv=argv,exit_code=result.returncode,output=label+'.log'));save()
        if result.returncode:raise RuntimeError(label+': '+result.stderr[-2400:])
        return result.stdout
    try:
        run(['python3',device/'tools/prepare_sheng_stylus_swap.py','--work',out],'swap-policy')
        run(['python3',device/'tools/build_sheng_pen_settings.py','--output',out/'settings',
             '--preaudit',args.preaudit],'settings-build')
        settings=json.loads((out/'settings/build-receipt.json').read_text())
        assert settings['platform_certificate_unchanged'] and settings['api1_bootstrap_compile_passed']
        api=source/'aidl_api/vendor.lineage.sheng.stylus/1'
        frozen_hash=(api/'.hash').read_text().strip()
        assert frozen_hash==baseline['frozen_api_hash']
        run(['bash',rom/'system/tools/aidl/build/hash_gen.sh',api,'latest-version',native/'api.hash'],'api-hash')
        assert (native/'api.hash').read_text().strip()==frozen_hash
        run([host/'aidl','--structured','--stability=vintf','--version=1','--hash='+frozen_hash,
             '--min_sdk_version=35','-I'+str(api),'--lang=java','--out='+str(native/'generated'),
             api/'vendor/lineage/sheng/stylus/IPenController.aidl'],'aidl-java')
        jars=[rom/'out/soong/.intermediates/frameworks/base/framework-minus-apex/android_common/combined/framework.jar',
              rom/'out/soong/.intermediates/packages/modules/Bluetooth/framework/framework-bluetooth.impl/android_common/combined/framework-bluetooth.jar',
              rom/'out/soong/.intermediates/libcore/core-libart/android_common_apex31/javac/core-libart.jar']
        receipt['classpath_sha256']={str(path):sha(path) for path in jars}
        java_sources=[path for root in (source/'src',source/'app',pen/'common',native/'generated') for path in root.rglob('*.java')]
        run([jdk/'javac','-J-Xmx384m','-source','8','-target','8','-Xlint:-options','-encoding','UTF-8',
             '-cp',os.pathsep.join(map(str,jars)),'-d',native/'classes',*java_sources],'stylus-java')
        classes=native/'classes.jar'
        with zipfile.ZipFile(classes,'w',zipfile.ZIP_DEFLATED) as archive:
            for path in sorted((native/'classes').rglob('*.class')):archive.write(path,path.relative_to(native/'classes').as_posix())
        sdk=rom/'prebuilts/sdk/37.0/public/android.jar';dex=native/'dex';dex.mkdir()
        command=[jdk/'java','-Xmx384m','-cp',rom/'prebuilts/r8/r8.jar','com.android.tools.r8.D8',
                 '--release','--lib',sdk,'--min-api','35','--output',dex]
        for path in jars:command+=['--classpath',path]
        run([*command,classes],'stylus-dex')
        run([host/'aapt2','link','-I',sdk,'--manifest',source/'AndroidManifest.xml',
             '--min-sdk-version','35','--target-sdk-version','37','-o',native/'resources.apk'],'stylus-manifest')
        with zipfile.ZipFile(native/'resources.apk') as old,zipfile.ZipFile(native/'unsigned.apk','w') as archive:
            for entry in old.infolist():archive.writestr(entry,old.read(entry.filename))
            for path in dex.glob('*.dex'):archive.write(path,path.name,compress_type=zipfile.ZIP_STORED)
        run([host/'zipalign','-P','16','-f','4',native/'unsigned.apk',native/'aligned.apk'],'stylus-align')
        apk=product/'product/priv-app/ShengStylus/ShengStylus.apk';apk.parent.mkdir(parents=True)
        security=rom/'build/target/product/security';signer=rom/'prebuilts/sdk/tools/linux/lib/apksigner.jar'
        run([jdk/'java','-Xmx256m','-jar',signer,'sign','--key',security/'platform.pk8','--cert',security/'platform.x509.pem',
             '--min-sdk-version','35','--out',apk,native/'aligned.apk'],'stylus-sign')
        run([jdk/'java','-Xmx256m','-jar',signer,'verify','--verbose','--print-certs',apk],'stylus-signature')
        run([host/'zipalign','-c','-P','16','4',apk],'stylus-alignment-check')
        settings_apk=product/'product/app/ShengPenSettings/ShengPenSettings.apk';settings_apk.parent.mkdir(parents=True)
        shutil.copyfile(out/'settings/ShengPenSettings.apk',settings_apk)
        apks=[apk,settings_apk]
        if args.include_ime:
            metadata=json.loads((ime/'source.json').read_text()); original=ime/'proprietary/SogouIme.apk'
            assert original.stat().st_size==metadata['bytes'] and sha(original)==metadata['sha256']
            signature=run([jdk/'java','-Xmx256m','-jar',signer,'verify','--verbose','--print-certs',original],'ime-signature')
            assert 'certificate SHA-256 digest: '+metadata['certificate_sha256'] in signature
            run(['python3',rom/'build/soong/scripts/check_prebuilt_presigned_apk.py','--preprocessed',
                 '--aapt2',host/'aapt2','--zipalign',host/'zipalign',original,native/'ime-preprocessed.stamp'],
                'ime-preprocessed-check')
            ime_apk=product/'product/app/ShengSogouIme/ShengSogouIme.apk';ime_apk.parent.mkdir(parents=True)
            shutil.copyfile(original,ime_apk);apks.append(ime_apk)
            receipt['ime_original_signature_preserved']=True
        assert snapshot()==before
        receipt.update(passed=True,api_frozen=True,frozen_api_hash=frozen_hash,apk_files={
            str(path.relative_to(product)):dict(bytes=path.stat().st_size,sha256=sha(path)) for path in apks},
            settings_receipt_sha256=sha(out/'settings/build-receipt.json'),preaudit_sha256=sha(args.preaudit))
    except BaseException as error:
        receipt['error']=repr(error);raise
    finally:
        receipt['finished_utc']=datetime.now(timezone.utc).isoformat();save()
    print(json.dumps(dict(passed=True,output=str(out),apks=receipt['apk_files']),indent=2))

if __name__=='__main__':main()
