#!/usr/bin/env python3
"""Build and verify an isolated pen page, including its API 1 Settings entry."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, default=Path('/root/sheng-lineage/lineage-24.0'))
    parser.add_argument('--output', type=Path, required=True,
                        help='New artifact directory; an existing directory is never overwritten')
    validation = parser.add_mutually_exclusive_group(required=True)
    validation.add_argument('--preaudit', type=Path)
    validation.add_argument('--software-receipt', type=Path)
    parser.add_argument('--out', default='out')
    parser.add_argument('--build-root', type=Path)
    parser.add_argument('--reference-apk', type=Path,
                        help='Installed platform-signed pen APK for certificate continuity checks')
    args = parser.parse_args()
    device = Path(__file__).resolve().parents[1]
    source = device / 'interfaces/input/pen'
    validation_path = args.preaudit or args.software_receipt
    audit = json.loads(validation_path.read_text())
    if args.preaudit:
        assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
        assert 0 <= datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(audit['date_utc']).timestamp() < 7200
    else:
        assert audit['passed'] and not audit['hardware_tested']
        workspace = device.parents[2]
        for path in source.rglob('*'):
            if path.is_file():
                assert audit['source_sha256'][str(path.relative_to(workspace))] == sha(path), path
    artifact = args.output.resolve()
    artifact.mkdir(parents=True, exist_ok=False)
    rom = args.rom.resolve(strict=True)
    build = Path(tempfile.mkdtemp(prefix='pen-settings-', dir=args.build_root or rom.parent))
    classes, dex, generated, legacy = [build / name for name in
                                       ('classes', 'dex', 'generated', 'api1-bootstrap')]
    for directory in (classes, dex, generated, legacy):
        directory.mkdir()
    java = rom / 'prebuilts/jdk/jdk21/linux-x86/bin'
    host = rom / args.out / 'host/linux-x86'
    framework = rom / args.out / 'soong/.intermediates/frameworks/base/framework-minus-apex/android_common/combined/framework.jar'
    sdk = rom / 'prebuilts/sdk/37.0/public/android.jar'
    system_sdk = rom / 'prebuilts/sdk/current/system/android.jar'
    old_sdk = rom / 'prebuilts/sdk/1/public/android.jar'
    sdk_audit = {}
    for jar in (sdk, old_sdk):
        relative = jar.relative_to(rom / 'prebuilts/sdk').as_posix()
        expected = subprocess.check_output(['git', '-C', rom / 'prebuilts/sdk',
                                            'rev-parse', 'HEAD:' + relative], text=True).strip()
        raw = jar.read_bytes()
        actual = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        assert actual == expected, jar
        sdk_audit[relative] = {'expected_blob': expected, 'actual_blob': actual, 'sha256': sha(jar)}
    env = dict(os.environ, LANG='C.UTF-8', LC_ALL='C.UTF-8',
               LD_LIBRARY_PATH=str(host / 'lib64'))
    commands = []

    def run(command):
        result = subprocess.run(list(map(str, command)), env=env, text=True, capture_output=True)
        commands.append({'argv': list(map(str, command)), 'returncode': result.returncode,
                         'stdout': result.stdout, 'stderr': result.stderr})
        (artifact / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return result.stdout + result.stderr

    aapt = host / 'bin/aapt2'
    compiled, resources = build / 'resources.zip', build / 'resources.apk'
    run([aapt, 'compile', '--dir', source / 'res', '-o', compiled])
    run([aapt, 'link', '-I', sdk, '--manifest', source / 'AndroidManifest.xml',
         '--min-sdk-version', '1', '--target-sdk-version', '37',
         '--java', generated, '-o', resources, compiled])
    bootstrap = source / 'src/org/lineageos/sheng/pen/CompatibilityActivity.java'
    run([java / 'javac', '-source', '8', '-target', '8', '-encoding', 'UTF-8',
         '-classpath', old_sdk, '-d', legacy, bootstrap, *generated.rglob('*.java')])
    run([java / 'javac', '-source', '8', '-target', '8', '-encoding', 'UTF-8',
         '-cp', str(framework) + ':' + str(system_sdk), '-d', classes,
         *source.rglob('*.java'), *generated.rglob('*.java')])
    class_jar = build / 'classes.jar'
    with zipfile.ZipFile(class_jar, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in classes.rglob('*.class'):
            archive.write(path, path.relative_to(classes).as_posix())
    run([java / 'java', '-cp', rom / 'prebuilts/r8/r8.jar', 'com.android.tools.r8.D8',
         '--release', '--lib', sdk, '--min-api', '1', '--output', dex, class_jar])
    unsigned = build / 'ShengPenSettings-unsigned.apk'
    with zipfile.ZipFile(resources) as original, zipfile.ZipFile(unsigned, 'w') as output:
        for item in original.infolist():
            output.writestr(item, original.read(item.filename))
        for path in sorted(dex.glob('*.dex')):
            assert path.read_bytes()[:8] == b'dex\n035\0'
            output.write(path, path.name, compress_type=zipfile.ZIP_STORED)
    aligned, candidate = build / 'ShengPenSettings-aligned.apk', artifact / 'ShengPenSettings.apk'
    run([host / 'bin/zipalign', '-P', '16', '-f', '4', unsigned, aligned])
    signer, security = host / 'framework/apksigner.jar', rom / 'build/target/product/security'
    run([java / 'java', '-jar', signer, 'sign', '--key', security / 'platform.pk8',
         '--cert', security / 'platform.x509.pem', '--min-sdk-version', '1',
         '--v1-signing-enabled', 'true', '--v2-signing-enabled', 'true',
         '--v3-signing-enabled', 'true', '--out', candidate, aligned])
    verification = run([java / 'java', '-jar', signer, 'verify', '--verbose', '--print-certs',
                        '--min-sdk-version', '1', candidate])
    assert 'Verified using v1 scheme (JAR signing): true' in verification
    run([host / 'bin/zipalign', '-c', '-P', '16', '4', candidate])
    old = args.reference_apk or device.parents[2] / 'artifacts/pen-settings-sheng-r53/ShengPenSettings.apk'
    old_verification = run([java / 'java', '-jar', signer, 'verify', '--print-certs', old])
    cert = lambda text: re.search(r'certificate SHA-256 digest: ([0-9a-f]+)', text).group(1)
    assert cert(verification) == cert(old_verification)
    manifest = run([aapt, 'dump', 'xmltree', candidate, '--file', 'AndroidManifest.xml'])
    # A queries/intent may legitimately enumerate user-selected apps. Check
    # the packaged launchable activity instead of banning that string globally.
    badging = run([aapt, 'dump', 'badging', candidate])
    assert not re.search(r'^launchable-activity:', badging, re.MULTILINE)
    assert 'com.android.settings.action.EXTRA_SETTINGS' in manifest
    (artifact / 'manifest.txt').write_text(manifest)
    (artifact / 'resources.txt').write_text(run([aapt, 'dump', 'resources', candidate]))
    (artifact / 'signature.txt').write_text(verification)
    with zipfile.ZipFile(candidate) as archive:
        assert all(archive.read(name)[:8] == b'dex\n035\0'
                   for name in archive.namelist() if name.endswith('.dex'))
    receipt = {'date_utc': datetime.now(timezone.utc).isoformat(),
               'kind': 'isolated-pen-settings-candidate', 'installed': False,
               'product_build_completed': False, 'normal_module_build_passed': False,
               'hardware_writes': False, 'hardware_page_tested': False,
               'api1_bootstrap_compile_passed': True, 'api1_runtime_tested': False,
               'dex_version': '035', 'v1_signature_verified': True,
               'platform_certificate_unchanged': True, 'settings_entry_present': True,
               'launcher_entry_present': False, 'sdk_byte_audit': sdk_audit,
               'apk_sha256': sha(candidate), 'source': {
                   str(p.relative_to(source)): sha(p) for p in source.rglob('*') if p.is_file()},
               'builder_sha256': sha(Path(__file__)), 'validation_sha256': sha(validation_path),
               'validation_kind': 'public-source-audit' if args.preaudit else 'pen-software-tests',
               'build_directory': str(build)}
    if args.software_receipt:
        for path in source.rglob('*'):
            if path.is_file():
                assert audit['source_sha256'][str(path.relative_to(workspace))] == sha(path), path
    (artifact / 'build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(candidate)
    print('SHA256=' + sha(candidate))


if __name__ == '__main__':
    main()
