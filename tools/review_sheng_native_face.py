#!/usr/bin/env python3
"""Review final native Face build inputs and camera-free host checks."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile

SCOPE = {
    'system_ext': [
        'priv-app/ShengFaceUnlock/ShengFaceUnlock.apk',
        'etc/permissions/privapp-permissions-org.lineageos.sheng.faceunlock.xml',
        'framework/ShengNativeFaceBootstrap.jar', 'bin/sheng-face',
        'etc/init/sheng-face.rc',
        'etc/selinux/system_ext_sepolicy.cil',
        'etc/selinux/system_ext_sepolicy_and_mapping.sha256',
        'etc/selinux/system_ext_file_contexts',
        'etc/selinux/system_ext_property_contexts',
    ],
    'odm': ['overlay/FrameworkResOverlaySheng.apk', 'overlay/SettingsResOverlaySheng.apk',
            'etc/vintf/manifest/face-native.xml'],
    'vendor': ['etc/permissions/android.hardware.biometrics.face.xml'],
}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--revision', type=int, choices=[44,45,46], default=44)
    parser.add_argument('--rom', type=Path, default=Path('/root/sheng-lineage/lineage-24.0'))
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--build-log', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--platform-apk', type=Path, required=True)
    parser.add_argument('--platform-runtime', type=Path, required=True)
    args = parser.parse_args()
    if args.revision >= 46:
        SCOPE['system_ext'].append('etc/selinux/system_ext_keystore2_key_contexts')
    assert __debug__
    args.work.mkdir(exist_ok=False)
    rom, product = args.rom, args.rom / 'out/target/product/sheng'
    device = Path('device/xiaomi/sheng')
    feature = device / 'interfaces/biometrics/systemface'
    shared = device / 'interfaces/biometrics/softwareface'
    inputs = json.loads((args.workspace / 'reports/device/20261110-resume/face-native/backend-source-inputs.json').read_text())
    for relative, digest in inputs.items():
        assert sha(args.workspace / relative) == sha(rom / relative) == digest, relative
    audit = json.loads(args.audit.read_text())
    assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
    assert datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(audit['date_utc']).timestamp() < 7200
    assert '#### build completed successfully' in args.build_log.read_text()
    assert (rom / 'out/host/linux-x86/bin/soong_build').read_bytes()[:4] == b'\x7fELF'
    assert sha(args.platform_runtime) == '4ed3af57b6335c0e30fead26383ee7867bea9027695a9542b98297b3880221ec'
    jdk = rom / 'prebuilts/jdk/jdk21/linux-x86/bin'
    host = rom / 'out/host/linux-x86/bin'
    commands = []
    def run(argv):
        r = subprocess.run(list(map(str, argv)), text=True, capture_output=True,
                           env={**os.environ, 'LC_ALL': 'C.UTF-8', 'LANG': 'C.UTF-8'})
        commands.append(dict(argv=list(map(str, argv)), returncode=r.returncode,
                             stdout=r.stdout, stderr=r.stderr))
        (args.work / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        assert r.returncode == 0, r.stdout + r.stderr
        return r.stdout
    signer = rom / 'prebuilts/sdk/tools/linux/lib/apksigner.jar'
    assert sha(args.platform_apk) == '33017b0d59e28da5db3e089a98f49601de508228a012392ee2d04c82cda3ccb1'
    def certificate(apk, api=30):
        output = run([jdk/'java', '-jar', signer, 'verify', '--verbose', '--print-certs', '--min-sdk-version', api, apk])
        if api == 1: assert 'Verified using v1 scheme (JAR signing): true' in output
        return re.search(r'certificate SHA-256 digest: ([0-9a-f]+)', output).group(1)
    platform = certificate(args.platform_apk)
    modern = product / 'system_ext' / SCOPE['system_ext'][0]
    launcher = product/'system_ext/bin/sheng-face'
    assert launcher.read_bytes()[:5] == b'\x7fELF\x02'
    dynamic = run([rom/'prebuilts/clang/host/linux-x86/llvm-binutils-stable/llvm-readelf','-d',launcher])
    assert 'libandroid_runtime.so' in dynamic and 'libsigchain.so' in dynamic
    needed = re.findall(r'Shared library: \[([^\]]+)\]',dynamic)
    assert needed.index('libsigchain.so') < needed.index('libc.so')
    reader=rom/'prebuilts/clang/host/linux-x86/llvm-binutils-stable/llvm-readelf'
    symbols=run([reader,'--dyn-syms','--wide',launcher])
    required_runtime={line.split()[-1].split('@')[0] for line in symbols.splitlines()
                      if ' UND ' in line and 'AndroidRuntime' in line}
    symbols=run([reader,'--dyn-syms','--wide',args.platform_runtime])
    runtime_exports={line.split()[-1].split('@')[0] for line in symbols.splitlines()
                     if 'AndroidRuntime' in line and ' UND ' not in line}
    assert required_runtime and required_runtime <= runtime_exports
    legacy = rom / 'out/soong/.intermediates' / feature / 'ShengFaceUnlockLegacy/android_common/ShengFaceUnlockLegacy.apk'
    for apk, api in [(modern,30), (legacy,1)]:
        assert certificate(apk,api) == platform
        run([host/'zipalign','-c','-P','16','4',apk])
        badging = run([host/'aapt2','dump','badging',apk])
        assert re.search(rf"(?m)^(?:sdkVersion|minSdkVersion):'{api}'$",badging)
        assert 'launchable-activity:' not in badging
        manifest = run([host/'aapt2','dump','xmltree',apk,'--file','AndroidManifest.xml'])
        if api == 30:
            for value in ['android.uid.system','CAMERA','ACCESS_KEYGUARD_SECURE_STORAGE','OBSERVE_SENSOR_PRIVACY']:
                assert value in manifest, value
            for value in ['E: activity','E: service','E: receiver','EXTRA_SETTINGS','BIND_TRUST_AGENT','WRITE_SECURE_SETTINGS']:
                assert value not in manifest, value
        else:
            assert 'E: uses-permission' not in manifest and 'E: service' not in manifest and 'sharedUserId' not in manifest
            with zipfile.ZipFile(apk) as z:
                assert z.read('classes.dex')[:8] == b'dex\n035\0'
                assert not any(x.startswith(('lib/','assets/models/')) for x in z.namelist())
    dependencies = json.loads((rom/shared/'engine-dependencies.json').read_text())
    assets = rom/feature/'cache/engine/assets'
    with zipfile.ZipFile(modern) as z:
        for path in assets.rglob('*'):
            if path.is_file(): assert z.read('assets/'+path.relative_to(assets).as_posix()) == path.read_bytes()
        for name,digest in [('libopencv_java4.so',dependencies['files_sha256']['libopencv_java4.so']),
                            ('libc++_shared.so',dependencies['libcxx_shared_sha256'])]:
            entry=z.getinfo('lib/arm64-v8a/'+name)
            assert entry.compress_type==zipfile.ZIP_STORED
            assert hashlib.sha256(z.read(entry)).hexdigest()==digest
        assert {x.split('/')[1] for x in z.namelist() if x.startswith('lib/')}=={'arm64-v8a'}
    make = (rom/'out/soong/Android-lineage_sheng.mk').read_text()
    # Non-installed cc libraries may be omitted entirely from AndroidMk. When
    # exported, their rule must still declare no installed payload.
    signal_parts=make.split('LOCAL_MODULE := sheng-native-art-signal-link\n',1)
    if len(signal_parts)==2:
        signal_rule=signal_parts[1].split('include $(CLEAR_VARS)',1)[0]
        assert 'LOCAL_SOONG_INSTALLED_MODULE :=' not in signal_rule and 'LOCAL_SOONG_INSTALL_PAIRS :=' not in signal_rule
    assert not (product/'system_ext/lib64/libsigchain.so').exists()
    rule=make.split('LOCAL_MODULE := ShengFaceUnlockLegacy\n',1)[1].split('include $(CLEAR_VARS)',1)[0]
    assert 'LOCAL_SOONG_INSTALLED_MODULE :=' not in rule and 'LOCAL_SOONG_INSTALL_PAIRS :=' not in rule
    tests=args.work/'host-tests';tests.mkdir()
    pure=[rom/shared/'src/org/lineageos/sheng/facelab'/name for name in
          ['FrameMath.java','FaceDescriptor.java','SampleCollector.java','AnalysisGate.java','PreviewGeometry.java',
           'EnrollmentFraming.java','EnrollmentRequest.java','FaceEmbedding.java','FaceLandmarkPose.java']]
    pure += [rom/feature/'src/org/lineageos/sheng/facelab/MatchSession.java',
             rom/feature/'native/src/org/lineageos/sheng/face/ChallengeLedger.java',
             rom/feature/'native/src/org/lineageos/sheng/face/EnrollmentPoseGate.java']
    suites=sorted((rom/shared/'tests').glob('*.java'))+sorted((rom/feature/'tests').glob('*.java'))
    suites += [rom/feature/'native/tests/ChallengeLedgerTests.java',rom/feature/'native/tests/EnrollmentPoseTests.java']
    run([jdk/'javac','--release','11','-encoding','UTF-8','-d',tests,*pure,*suites])
    checks=[]
    for test in suites:
        package=re.search(r'package ([^;]+);',test.read_text()).group(1)
        checks.append(run([jdk/'java','-cp',tests,package+'.'+test.stem]).strip())
    compat=args.work/'api1-classes';compat.mkdir()
    run([jdk/'javac','-source','8','-target','8','-encoding','UTF-8','-bootclasspath',rom/'prebuilts/sdk/1/public/android.jar',
         '-d',compat,*sorted((rom/feature/'compat/src').rglob('*.java'))])
    manifest=ET.parse(product/'odm/etc/vintf/manifest/face-native.xml').getroot()
    assert not (product/'system_ext/etc/vintf/manifest/face-native.xml').exists(), \
        'Remove the rejected generated system_ext fragment before building a product image'
    hal=manifest.find('hal');assert hal.findtext('name')=='android.hardware.biometrics.face' and hal.findtext('version')=='5'
    assert hal.findtext('fqname')=='IFace/default'
    featurexml=ET.parse(product/'vendor/etc/permissions/android.hardware.biometrics.face.xml').getroot()
    assert featurexml.find('feature').get('name')=='android.hardware.biometrics.face'
    cil=(product/'system_ext/etc/selinux/system_ext_sepolicy.cil').read_text()
    assert '(type sheng_face)' in cil and 'sheng_face_data_file' in cil
    if args.revision >= 46:
        assert '(type sheng_face_key)' in cil
        contexts = (product/'system_ext/etc/selinux/system_ext_keystore2_key_contexts').read_text()
        assert [p.split() for p in contexts.splitlines() if p.strip() and not p.lstrip().startswith('#')] == [['10001','u:object_r:sheng_face_key:s0']]
        assert "versionCode='4'" in run([host/'aapt2','dump','badging',modern])
    entries={part:{rel:dict(source=str(product/part/rel),kind='file',bytes=(product/part/rel).stat().st_size,
                           sha256=sha(product/part/rel)) for rel in paths} for part,paths in SCOPE.items()}
    report=dict(date_utc=datetime.now(timezone.utc).isoformat(),revision=args.revision,normal_module_build_passed=True,
                full_product_build_passed=False,api1_bootstrap_compile_passed=True,api1_runtime_tested=False,
                native_and_model_payload_verified=True,native_manifest_without_app_components=True,
                sources_sha256=inputs,entries=entries,synthetic_checks=checks,platform_certificate=platform,
                build_log_sha256=sha(args.build_log),audit_sha256=sha(args.audit),
                original_platform_runtime_sha256=sha(args.platform_runtime),
                native_runtime_abi_symbols=sorted(required_runtime),
                camera_opened_by_agent=False,native_settings_enrollment_tested=False,keyguard_authentication_tested=False)
    (args.work/'build-review.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'native_build_review_passed':True,'checks':checks,'apk_sha256':sha(modern)}))

if __name__=='__main__': main()
