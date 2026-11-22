#!/usr/bin/env python3
"""Verify the normally built Dolby APK without modifying or installing it."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from sheng_apk_components import verify_apk_components


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--previous-apk', type=Path, required=True)
    parser.add_argument('--build-log', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--mirror', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rom = args.rom.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    apk = rom / 'out/target/product/sheng/product/priv-app/ShengDolby/ShengDolby.apk'
    assert '#### build completed successfully' in args.build_log.read_text()
    audit = json.loads(args.audit.read_text())
    assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
    age = datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(audit['date_utc']).timestamp()
    assert 0 <= age < 7200
    mirror = json.loads(args.mirror.read_text())
    assert mirror['passed'] and mirror['scopes'] == ['dolby/ShengDolby']
    assert not mirror['unexpected_mirror_inputs']
    for name, entry in mirror['inputs'].items():
        assert entry['kind'] == 'file'
        assert sha(rom / name) == sha(Path(mirror['workspace']) / name) == entry['sha256'], name
    host = rom / 'out/host/linux-x86/bin'
    env = dict(os.environ, LANG='C.UTF-8', LC_ALL='C.UTF-8',
               LD_LIBRARY_PATH=str(host.parent / 'lib64'))
    commands = []

    def run(argv, filename):
        command_env = dict(env)
        if Path(argv[0]).name == 'java':
            # The SDK signer bundles its own Conscrypt. Host ELF libraries can
            # supply a different JNI ABI, so retain the signer's own search path.
            command_env.pop('LD_LIBRARY_PATH', None)
        result = subprocess.run(list(map(str, argv)), cwd=rom, capture_output=True,
                                text=True, env=command_env)
        commands.append(dict(argv=list(map(str, argv)), returncode=result.returncode, output=filename))
        (output / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        (output / filename).write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stderr
        return result.stdout + result.stderr

    badging = run([host / 'aapt2', 'dump', 'badging', apk], 'badging.txt')
    assert re.search(r"^(?:minSdkVersion|sdkVersion):'1'$", badging, re.MULTILINE)
    assert re.search(r"^targetSdkVersion:'37'$", badging, re.MULTILINE)
    source_manifest = (rom / 'device/xiaomi/sheng/dolby/ShengDolby/AndroidManifest.xml').read_text()
    source_root = ET.fromstring(source_manifest)
    android_ns = '{http://schemas.android.com/apk/res/android}'
    version_code = source_root.attrib[android_ns + 'versionCode']
    version_name = source_root.attrib[android_ns + 'versionName']
    assert ("package: name='" + source_root.attrib['package'] + "' versionCode='" + version_code
            + "' versionName='" + version_name + "'") in badging
    manifest = run([host / 'aapt2', 'dump', 'xmltree', apk, '--file', 'AndroidManifest.xml'], 'manifest.txt')
    components = verify_apk_components(apk, manifest,
        source_manifest)
    for required in ('com.android.settings.action.EXTRA_SETTINGS',
                     'android.media.action.DISPLAY_AUDIO_EFFECT_CONTROL_PANEL',
                     'com.android.settings.category.ia.sound', 'CompatibilityApplication',
                     'CompatibilityActivity'):
        assert required in manifest, required
    for attribute in ('persistent', 'directBootAware'):
        assert re.search(r'A: (?:android|http://schemas\.android\.com/apk/res/android):'
                         + attribute + r'\(0x[0-9a-f]+\)=(?:true|\(type 0x12\)0xffffffff)\s*$',
                         manifest, re.MULTILINE), attribute
    assert 'android.intent.category.LAUNCHER' not in manifest and 'CAMERA' not in manifest
    signer = rom / 'prebuilts/sdk/tools/linux/lib/apksigner.jar'
    java = rom / 'prebuilts/jdk/jdk21/linux-x86/bin/java'
    signature = run([java, '-jar', signer, 'verify', '--verbose', '--print-certs',
                     '--min-sdk-version', '1', apk], 'signature.txt')
    assert 'Verified using v1 scheme (JAR signing): true' in signature
    certificate = re.search(r'certificate SHA-256 digest: ([0-9a-f]+)', signature).group(1)
    pem = (rom / 'build/target/product/security/platform.x509.pem').read_text()
    assert certificate == hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()
    previous_signature = run([java, '-jar', signer, 'verify', '--print-certs',
                              '--min-sdk-version', '1', args.previous_apk], 'previous-signature.txt')
    assert re.search(r'certificate SHA-256 digest: ([0-9a-f]+)', previous_signature).group(1) == certificate
    run([host / 'zipalign', '-c', '-P', '16', '4', apk], 'zipalign.txt')
    dex_dump = run([host / 'dexdump', apk], 'dex.txt')
    match = re.search(r"Class descriptor\s*: 'Lorg/lineageos/sheng/dolby/AtmosApplication;'\n(.*?)(?=\nClass #|\Z)", dex_dump, re.DOTALL)
    assert match, 'AtmosApplication removed or renamed'
    assert re.search(r"name\s*: '<init>'\s*\n\s*type\s*: '\(Landroid/content/Context;\)V'\s*\n\s*access\s*: [^\n]*\bPUBLIC\b", match.group(1)), 'Reflected public Context constructor missing'
    with zipfile.ZipFile(apk) as archive, zipfile.ZipFile(args.previous_apk) as previous:
        dex = {name: hashlib.sha256(archive.read(name)).hexdigest()
               for name in archive.namelist() if name.endswith('.dex')}
        assert dex and all(archive.read(name)[:8] == b'dex\n035\0' for name in dex)
        previous_dex = {name: hashlib.sha256(previous.read(name)).hexdigest()
                        for name in previous.namelist() if name.endswith('.dex')}
        changed_entries = sorted(name for name in set(archive.namelist()) | set(previous.namelist())
                                 if name not in archive.namelist() or name not in previous.namelist()
                                 or archive.read(name) != previous.read(name))
    # Ninja targets remain relative to the ROM root even when its graph path is absolute.
    target = 'out/soong/.intermediates/device/xiaomi/sheng/dolby/ShengDolby/ShengDolby/android_common/ShengDolby.apk'
    result = subprocess.run([str(rom / 'prebuilts/build-tools/linux-x86/bin/ninja'), '-f',
                             'out/combined-lineage_sheng.ninja', '-t', 'commands', target],
                            cwd=rom, capture_output=True, text=True, check=True)
    links = [line for line in result.stdout.splitlines() if 'ShengDolby' in line and '--target-sdk-version' in line]
    # Pinned Soong java/aar.go intentionally uses the minimum SDK for both
    # aapt2 defaults. The effective app target comes from manifest_fixer/XML.
    assert len(links) == 1 and '--min-sdk-version 1 ' in links[0] and '--target-sdk-version 1 ' in links[0]
    (output / 'aapt-link-after.txt').write_text(links[0] + '\n')
    fixers = [line for line in result.stdout.splitlines() if 'bin/manifest_fixer ' in line and 'ShengDolby' in line]
    assert len(fixers) == 1 and re.search(r'--targetSdkVersion\s+37\b', fixers[0])
    assert re.search(r'--minSdkVersion\s+1\b', fixers[0])
    (output / 'manifest-fixer-command.txt').write_text(fixers[0] + '\n')
    report = dict(date_utc=datetime.now(timezone.utc).isoformat(), normal_module_build_passed=True,
                  version_code=int(version_code), version_name=version_name,
                  component_class_contract=components,
                  full_product_build_passed=False, installed_new_apk=False, hardware_audio_retested=False,
                  min_sdk_version=1, target_sdk_version=37, dex_version='035', v1_signature_verified=True,
                  aapt_target_sdk_default=1, aapt_default_follows_minimum_intentionally=True,
                  manifest_fixer_target_sdk=37,
                  platform_certificate_verified=True, zipalign_16k_verified=True,
                  reflected_controller_constructor_retained=True, settings_entry_present=True,
                  audio_panel_entry_present=True, persistent_and_direct_boot=True,
                  launcher_entry_present=False, camera_permission_present=False,
                  apk_sha256=sha(apk), previous_apk_sha256=sha(args.previous_apk),
                  apk_identical_to_previous=sha(apk) == sha(args.previous_apk),
                  dex_sha256=dex, previous_dex_sha256=previous_dex,
                  dex_identical_to_previous=dex == previous_dex, changed_archive_entries=changed_entries,
                  inputs_sha256={name: entry['sha256'] for name, entry in mirror['inputs'].items()},
                  audit_sha256=sha(args.audit), mirror_sha256=sha(args.mirror), build_log_sha256=sha(args.build_log),
                  verifier_sha256=sha(Path(__file__)))
    (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'inputs_sha256'}, indent=2))


if __name__ == '__main__':
    main()
