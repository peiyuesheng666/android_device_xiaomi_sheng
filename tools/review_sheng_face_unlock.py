#!/usr/bin/env python3
"""Verify normal FaceUnlock modules and synthetic checks without opening a camera."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile
import xml.etree.ElementTree as ET


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--rom', type=Path, default=Path('/root/sheng-lineage/lineage-24.0'))
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--build-log', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--platform-apk', type=Path, required=True,
                        help='Byte-verified original SystemUI from the accepted device/image')
    args = parser.parse_args()
    assert __debug__
    rom, work = args.rom.resolve(), args.work.resolve()
    work.mkdir(exist_ok=False)
    device = Path('device/xiaomi/sheng')
    feature = device / 'interfaces/biometrics/systemface'
    shared = device / 'interfaces/biometrics/softwareface'
    sources = [p.relative_to(args.workspace) for d in (feature, shared, device / 'interfaces/display/defaults')
               for p in (args.workspace / d).rglob('*') if p.is_file()
               and 'cache' not in p.relative_to(args.workspace / d).parts]
    sources += [device / name for name in ('device.mk', 'tools/build_hardware.sh',
        'tools/prepare_sheng_face_engine.py', 'tools/review_sheng_face_unlock.py',
        'tools/package_sheng_face_unlock_r42.py', 'tools/flash_sheng_face_unlock_r42.ps1',
        'interfaces/biometrics/face/Android.bp')]
    source_hashes = {}
    for relative in sources:
        original, synced = args.workspace / relative, rom / relative
        assert original.read_bytes() == synced.read_bytes(), relative
        source_hashes[str(relative)] = sha(original)
    audit = json.loads(args.audit.read_text())
    assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
    assert datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(audit['date_utc']).timestamp() < 7200
    assert '#### build completed successfully' in args.build_log.read_text()
    product = rom / 'out/target/product/sheng'
    host = rom / 'out/host/linux-x86'
    jdk = rom / 'prebuilts/jdk/jdk21/linux-x86/bin'
    env = dict(os.environ, LC_ALL='C.UTF-8', LANG='C.UTF-8')
    commands = []
    def run(argv):
        result = subprocess.run(list(map(str, argv)), capture_output=True, text=True, env=env)
        commands.append(dict(command=list(map(str, argv)), returncode=result.returncode,
                             stdout=result.stdout, stderr=result.stderr))
        (work / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout
    modern = product / 'system_ext/priv-app/ShengFaceUnlock/ShengFaceUnlock.apk'
    legacy = rom / 'out/soong/.intermediates' / feature / 'ShengFaceUnlockLegacy/android_common/ShengFaceUnlockLegacy.apk'
    signer = rom / 'prebuilts/sdk/tools/linux/lib/apksigner.jar'
    certificates = {}
    for name, apk, api in [('modern', modern, 30), ('legacy', legacy, 1)]:
        signed = run([jdk / 'java', '-jar', signer, 'verify', '--verbose', '--print-certs',
                      '--min-sdk-version', api, apk])
        certificates[name] = re.search(r'certificate SHA-256 digest: ([0-9a-f]+)', signed).group(1)
        if api == 1: assert 'Verified using v1 scheme (JAR signing): true' in signed
        run([host / 'bin/zipalign', '-c', '-P', '16', '4', apk])
        badging = run([host / 'bin/aapt2', 'dump', 'badging', apk])
        assert re.search(rf"(?m)^(?:sdkVersion|minSdkVersion):'{api}'$", badging)
        assert 'launchable-activity:' not in badging
        assert "package: name='org.lineageos.sheng.faceunlock'" in badging
        manifest = run([host / 'bin/aapt2', 'dump', 'xmltree', apk, '--file', 'AndroidManifest.xml'])
        assert 'com.android.settings.action.EXTRA_SETTINGS' in manifest
        assert 'CompatibilityActivity' in manifest
        if api == 1:
            assert 'E: uses-permission' not in manifest and 'E: service' not in manifest
            assert 'sharedUserId' not in manifest
            with zipfile.ZipFile(apk) as archive:
                assert archive.read('classes.dex')[:8] == b'dex\n035\0'
                assert not any(n.startswith(('lib/', 'assets/models/')) for n in archive.namelist())
        else:
            for value in ('android.uid.system', 'BIND_TRUST_AGENT', 'OBSERVE_SENSOR_PRIVACY',
                          'WRITE_SECURE_SETTINGS', 'CAMERA', 'FaceUnlockService'):
                assert value in manifest, value
            assert 'android.intent.category.LAUNCHER' not in manifest
    # The final system APK must match the tablet's original platform signing identity.
    assert sha(args.platform_apk) == '33017b0d59e28da5db3e089a98f49601de508228a012392ee2d04c82cda3ccb1'
    platform = run([jdk / 'java', '-jar', signer, 'verify', '--print-certs', args.platform_apk])
    assert certificates['modern'] == certificates['legacy'] == re.search(
        r'certificate SHA-256 digest: ([0-9a-f]+)', platform).group(1)
    make = (rom / 'out/soong/Android-lineage_sheng.mk').read_text()
    legacy_rule = make.split('LOCAL_MODULE := ShengFaceUnlockLegacy\n', 1)[1].split('include $(CLEAR_VARS)', 1)[0]
    assert 'LOCAL_SOONG_INSTALLED_MODULE :=' not in legacy_rule
    assert 'LOCAL_SOONG_INSTALL_PAIRS :=' not in legacy_rule
    dependencies = json.loads((rom / shared / 'engine-dependencies.json').read_text())
    assets = rom / feature / 'cache/engine/assets'
    with zipfile.ZipFile(modern) as archive:
        for path in assets.rglob('*'):
            if path.is_file(): assert archive.read('assets/' + path.relative_to(assets).as_posix()) == path.read_bytes()
        for name, expected in [('libopencv_java4.so', dependencies['files_sha256']['libopencv_java4.so']),
                               ('libc++_shared.so', dependencies['libcxx_shared_sha256'])]:
            entry = archive.getinfo('lib/arm64-v8a/' + name)
            assert entry.compress_type == zipfile.ZIP_STORED
            assert hashlib.sha256(archive.read(entry)).hexdigest() == expected
        assert set(n.split('/')[1] for n in archive.namelist() if n.startswith('lib/')) == {'arm64-v8a'}
    # Test independent decision boundaries, stale/cancelled frames and shared enrollment math.
    classes = work / 'host-tests'; classes.mkdir()
    package = rom / shared / 'src/org/lineageos/sheng/facelab'
    pure = [package / name for name in ('FrameMath.java', 'FaceDescriptor.java', 'SampleCollector.java',
            'AnalysisGate.java', 'PreviewGeometry.java', 'EnrollmentFraming.java', 'EnrollmentRequest.java', 'FaceEmbedding.java')]
    pure += [rom / feature / 'src/org/lineageos/sheng/facelab/MatchSession.java']
    tests = sorted((rom / shared / 'tests').glob('*.java')) + sorted((rom / feature / 'tests').glob('*.java'))
    run([jdk / 'javac', '--release', '11', '-encoding', 'UTF-8', '-d', classes, *pure, *tests])
    checks = [run([jdk / 'java', '-cp', classes, 'org.lineageos.sheng.facelab.' + test.stem]).strip() for test in tests]
    compat = sorted((rom / feature / 'compat/src').rglob('*.java'))
    old = work / 'api1-classes'; old.mkdir()
    run([jdk / 'javac', '-source', '8', '-target', '8', '-encoding', 'UTF-8', '-bootclasspath',
         rom / 'prebuilts/sdk/1/public/android.jar', '-d', old, *compat])
    # Every retirement payload must be the normal installed copy target.
    scopes = {'system_ext': ['priv-app/ShengFaceUnlock/ShengFaceUnlock.apk',
                            'etc/permissions/privapp-permissions-org.lineageos.sheng.faceunlock.xml'],
              'odm': ['etc/init/android.hardware.biometrics.face-aidl-service.rc',
                      'etc/init/vendor.xiaomi.hardware.miface@1.0-service.rc',
                      'etc/vintf/manifest/face-default.xml',
                      'etc/vintf/manifest/manifest_vendor.xiaomi.hardware.miface.xml'],
              'vendor': ['etc/permissions/android.hardware.biometrics.face.xml']}
    entries = {part: {relative: dict(source=str(product / part / relative), kind='file',
                     bytes=(product / part / relative).stat().st_size, sha256=sha(product / part / relative))
                     for relative in paths} for part, paths in scopes.items()}
    for part in ('odm', 'vendor'):
        for relative in scopes[part]:
            if '/vintf/' in relative:
                root = ET.parse(product / part / relative).getroot()
                assert root.tag == 'manifest' and root.get('type') == 'device' and len(root) == 0
            else:
                original = 'face-service.rc' if relative.endswith('.rc') else 'permissions.xml'
                assert (product / part / relative).read_bytes() == (rom / feature / 'retired' / original).read_bytes()
    assert (product / 'system_ext' / scopes['system_ext'][1]).read_bytes() == (rom / feature / 'privapp-permissions.xml').read_bytes()
    report = dict(date_utc=datetime.now(timezone.utc).isoformat(), revision=42,
        normal_module_build_passed=True, full_product_build_passed=False, api1_bootstrap_compile_passed=True,
        api1_runtime_tested=False, synthetic_checks=checks, signatures=certificates,
        native_and_model_payload_verified=True, launcher_entry_present=False, settings_entry_present=True,
        original_systemui_sha256=sha(args.platform_apk), legacy_soong_install_disabled=True,
        sources_sha256=source_hashes, build_log_sha256=sha(args.build_log), audit_sha256=sha(args.audit),
        entries=entries, camera_opened=False, user_enrollment_tested=False, lockscreen_unlock_tested=False)
    (work / 'build-review.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'review_passed': True, 'checks': checks, 'modern_sha256': sha(modern)}))


if __name__ == '__main__': main()
