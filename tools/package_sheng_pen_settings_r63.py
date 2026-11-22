#!/usr/bin/env python3
"""Preinstall the normally built pen page over a sealed Android partition chain."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

from package_sheng_batch_helpers import (
    certificates, debugfs, merge_parent, publish_batch, stage_ext4, validate_inputs,
    verify_boot_policy,
)
from package_sheng_device_continue_r60 import split_policy_selection, UI_HASH
from package_sheng_model_followup import HOST, PRODUCT, ROM, sha

APP = 'app/ShengPenSettings/ShengPenSettings.apk'
SOURCE = Path('device/xiaomi/sheng/interfaces/input/pen')
PARTITIONS = {'system', 'system_ext', 'product', 'vendor', 'odm', 'vendor_dlkm',
              'system_dlkm', 'init_boot', 'boot', 'dtbo', 'recovery', 'vendor_boot',
              'vbmeta', 'vbmeta_system'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--build-run', type=Path, required=True)
    parser.add_argument('--compat-review', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--revision', type=int, choices=[63, 64], default=63)
    args = parser.parse_args()
    workspace = args.workspace.resolve(strict=True)
    build = args.build_run.resolve(strict=True)
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    assert shutil.disk_usage(work).free > 6 * 1024**3
    status = json.loads((build / 'status.json').read_text())
    assert status['normal_module_build_passed'] and status['postbuild_checks_completed']
    assert status['exit_code'] == 0 and status['last_phase'] == 'complete'
    assert status['modules'] == ['ShengPenSettings']
    assert '#### build completed successfully' in (build / 'build.log').read_text()
    assert (HOST / 'soong_build').read_bytes()[:4] == b'\x7fELF'
    audit_path = build / 'postbuild-upstream-audit.json'
    audit = json.loads(audit_path.read_text())
    assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
    assert 0 <= datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(
        audit['date_utc']).timestamp() < 7200
    mirror = json.loads((build / 'source-mirror.json').read_text())
    assert mirror['passed']
    sources = {str(p.relative_to(workspace)): sha(p)
               for p in (workspace / SOURCE).rglob('*') if p.is_file()}
    assert sources and set(sources) == {p for p in mirror['inputs'] if p.startswith(str(SOURCE) + '/')}
    compat_path = args.compat_review.resolve(strict=True)
    compat = json.loads(compat_path.read_text())
    assert compat['api1_bootstrap_compile_passed'] and not compat['api1_runtime_tested']
    assert {str(SOURCE / relative): digest for relative, digest in compat['source'].items()} == sources

    def check_sources():
        for relative, digest in sources.items():
            assert sha(workspace / relative) == sha(ROM / relative) == digest
            assert mirror['inputs'][relative]['sha256'] == digest
        for root in (workspace, ROM):
            assert 'PRODUCT_PACKAGES += ShengPenSettings' in (
                root / 'device/xiaomi/sheng/device.mk').read_text().splitlines()

    check_sources()
    apk = PRODUCT / 'system_ext' / APP
    assert (build / 'apk.sha256').read_text().split()[0] == sha(apk)
    commands = []

    def run(argv):
        result = subprocess.run(list(map(str, argv)), text=True, capture_output=True)
        commands.append(dict(argv=list(map(str, argv)), returncode=result.returncode,
                             stdout=result.stdout, stderr=result.stderr))
        (work / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    signer = ROM / 'prebuilts/sdk/tools/linux/lib/apksigner.jar'
    signature = run([ROM / 'prebuilts/jdk/jdk21/linux-x86/bin/java', '-jar', signer,
                     'verify', '--verbose', '--print-certs', '--min-sdk-version', '1', apk])
    assert 'Verified using v1 scheme (JAR signing): true' in signature
    run([HOST / 'zipalign', '-c', '-P', '16', '4', apk])
    manifest = run([HOST / 'aapt2', 'dump', 'xmltree', apk, '--file', 'AndroidManifest.xml'])
    badging = run([HOST / 'aapt2', 'dump', 'badging', apk])
    assert re.search(r"^(?:minSdkVersion|sdkVersion):'1'$", badging, re.MULTILINE)
    assert re.search(r"^targetSdkVersion:'37'$", badging, re.MULTILINE)
    assert 'com.android.settings.action.EXTRA_SETTINGS' in manifest
    category_source = ROM / 'frameworks/base/packages/SettingsLib/src/com/android/settingslib/drawer/CategoryKey.java'
    category = re.search(r'CATEGORY_CONNECT = "([^"]+)"', category_source.read_text()).group(1)
    assert f'"{category}"' in manifest, 'Settings cannot display an unregistered category'
    assert 'android.intent.category.LAUNCHER' not in manifest
    assert 'org.lineageos.sheng.pen' in manifest
    assert 'android.permission.BLUETOOTH_CONNECT' in manifest
    with zipfile.ZipFile(apk) as archive:
        dex = [name for name in archive.namelist() if name.endswith('.dex')]
        assert dex and all(archive.read(name)[:8] == b'dex\n035\0' for name in dex)
        assert not any(name.startswith('lib/') for name in archive.namelist())
    dex_dump = run([HOST / 'dexdump', apk])
    assert re.search(r"name\s*: 'supported'\s*\n\s*type\s*: '\(Landroid/content/Context;\)Z'", dex_dump), \
        'R8 removed or renamed the reflected modern-platform check'
    (work / 'signature.txt').write_text(signature)
    (work / 'manifest.txt').write_text(manifest)

    previous_path = workspace / f'artifacts/system-hardware-followup-sheng-r{args.revision - 1}/build-result.json'
    previous = json.loads(previous_path.read_text())
    assert previous['revision'] == args.revision - 1 and previous['complete_avb_chain_verified']
    assert previous['original_systemui_unchanged'] and previous['installed_qti_retained']
    assert previous['fingerprint_control_label_corrected'] and not previous['face_candidate_installed']
    baseline = [dict(entry, name=entry['partition'] + '.img') for entry in (
        previous['files'] + previous['unchanged_partition_files'] + previous['unchanged_boot_dependencies'])]
    assert len(baseline) == 14 and {entry['partition'] for entry in baseline} == PARTITIONS
    cache = Path(previous['work_dir']) / 'complete-chain'
    chain = {entry['partition']: cache / entry['name'] for entry in baseline}
    for entry in baseline:
        path = chain[entry['partition']]
        assert path.stat().st_size == entry['bytes'] and sha(path) == entry['sha256'], path
    reference = work / 'original-SystemUI.apk'
    debugfs(chain['system_ext'], f'dump /priv-app/SystemUI/SystemUI.apk {reference}')
    assert sha(reference) == UI_HASH
    assert certificates(apk) == certificates(reference)
    entries = {APP: dict(source=str(apk), kind='file', bytes=apk.stat().st_size, sha256=sha(apk))}
    validate_inputs('system_ext', entries)
    nodes = {relative: dict(uid=0, gid=0, mode=mode, mtime_ns=1230768000 * 10**9,
                           selinux='u:object_r:system_file:s0') for relative, mode in (
        ('app/ShengPenSettings', 0o755), (APP, 0o644))}
    if args.revision >= 64:
        nodes = {}
    replacement_mtimes = ({APP: int(datetime.fromisoformat(status['date_utc']).timestamp())}
                          if args.revision >= 64 else {})
    sys.path.insert(0, str(ROM / 'external/avb'))
    import avbtool
    avb = avbtool.Avb()
    image, tree, stage = stage_ext4('system_ext', chain['system_ext'], entries, nodes,
                                   work, avb, avbtool, certificates(reference),
                                   replacement_mtimes=replacement_mtimes)
    assert stage['changed_files'] == [APP] and stage['metadata_preserved']
    before, after = work / 'system_ext-before', work / 'system_ext-after'
    assert sha(after / 'priv-app/SystemUI/SystemUI.apk') == UI_HASH
    for directory in ('etc/selinux', 'etc/vintf'):
        for path in (before / directory).rglob('*'):
            if path.is_file():
                assert path.read_bytes() == (after / path.relative_to(before)).read_bytes()
    for part in ('vendor', 'odm'):
        run([HOST / 'fsck.erofs', '-d0', '--extract=' + str(work / (part + '-tree')),
             '--preserve', chain[part]])
    boot_policy = verify_boot_policy(chain, work)
    boot_policy.update(split_policy_selection(work))
    outputs = {'system_ext': image, 'vbmeta_system': work / 'vbmeta_system.img'}
    merge_parent(avb, avbtool, chain['vbmeta_system'], [tree], outputs['vbmeta_system'],
                 'SHA256_RSA2048', work)
    complete = work / 'complete-chain'
    complete.mkdir()
    for part, path in chain.items():
        (complete / (part + '.img')).symlink_to(outputs.get(part, path).resolve())
    run([HOST / 'avbtool', 'verify_image', '--image', complete / 'vbmeta.img', '--follow_chain_partitions'])
    check_sources()
    validate_inputs('system_ext', entries)
    publish_batch(workspace / f'artifacts/system-hardware-followup-sheng-r{args.revision}', outputs, dict(
        revision=args.revision, baseline_revision=args.revision - 1, baseline_partitions=baseline,
        baseline_manifest_sha256=sha(previous_path), entries={'system_ext': entries},
        unchanged_partition_files=[e for e in baseline if e['partition'] not in outputs],
        unchanged_boot_dependencies=[], partition_reports={'system_ext': stage},
        normal_module_build_passed=True, full_product_build_passed=False,
        all_filesystem_stages_verified=True, complete_avb_chain_verified=True,
        original_systemui_unchanged=True, installed_qti_retained=True,
        qti_source_service_integrated=False, retained_qti_sha256=previous['retained_qti_sha256'],
        fingerprint_control_label_corrected=True, face_candidate_installed=False,
        recovery_revision_retained=59, keyboard_r53_retained=True,
        pen_settings_preinstalled=True, settings_entry_present=True, launcher_entry_present=False,
        settings_category=category,
        min_sdk_version=1, target_sdk_version=37,
        dex_version='035', v1_signature_verified=True, platform_certificate_verified=True,
        api1_bootstrap_compile_passed=True, api1_runtime_tested=False,
        reflected_platform_check_retained=True,
        hardware_boot_tested=False, pen_page_tested=False, physical_pen_writing_tested=False,
        sources_sha256=sources, apk_sha256=sha(apk), boot_policy=boot_policy,
        build_status_sha256=sha(build / 'status.json'), build_log_sha256=sha(build / 'build.log'),
        source_mirror_sha256=sha(build / 'source-mirror.json'), post_audit_sha256=sha(audit_path),
        compatibility_review_sha256=sha(compat_path),
        work_dir=str(work), build_run=str(build)))
    print(f'Published r{args.revision}: normally built pen page in system_ext and matching vbmeta_system')


if __name__ == '__main__':
    main()
