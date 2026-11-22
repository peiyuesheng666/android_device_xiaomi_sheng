#!/usr/bin/env python3
"""Seal the reviewed software FaceUnlock and retired HAL over the accepted r41 chain."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from package_sheng_batch_helpers import (certificates, debugfs, merge_parent, publish_batch,
    stage_ext4, stage_erofs, validate_inputs)
from package_sheng_model_followup import HOST, PRODUCT, ROM, sha

SCOPE = {
    'system_ext': {'priv-app/ShengFaceUnlock/ShengFaceUnlock.apk',
                   'etc/permissions/privapp-permissions-org.lineageos.sheng.faceunlock.xml'},
    'odm': {'etc/init/android.hardware.biometrics.face-aidl-service.rc',
            'etc/init/vendor.xiaomi.hardware.miface@1.0-service.rc',
            'etc/vintf/manifest/face-default.xml', 'etc/vintf/manifest/manifest_vendor.xiaomi.hardware.miface.xml'},
    'vendor': {'etc/permissions/android.hardware.biometrics.face.xml'},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--build-review', type=Path, required=True)
    parser.add_argument('--post-audit', type=Path, required=True)
    args = parser.parse_args()
    assert __debug__
    workspace = args.workspace.resolve(strict=True)
    review, audit = json.loads(args.build_review.read_text()), json.loads(args.post_audit.read_text())
    assert review['revision'] == 42 and review['normal_module_build_passed']
    assert review['api1_bootstrap_compile_passed'] and review['native_and_model_payload_verified']
    assert review['settings_entry_present'] and not review['launcher_entry_present']
    assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
    assert datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(audit['date_utc']).timestamp() < 7200
    for relative, expected in review['sources_sha256'].items(): assert sha(workspace / relative) == expected, relative
    entries = review['entries']
    assert set(entries) == set(SCOPE)
    for part in SCOPE:
        assert set(entries[part]) == SCOPE[part]
        validate_inputs(part, entries[part])
    restoration = json.loads((workspace / 'reports/device/r38-restore-20261110/restore-manifest.json').read_text())
    assert restoration['complete_avb_chain_verified']
    chain_inputs = {}
    for entry in restoration['files']:
        path = workspace / entry['path']
        assert path.stat().st_size == entry['bytes'] and sha(path) == entry['sha256']
        chain_inputs[entry['partition']] = path
    for revision in (39, 40, 41):
        directory = workspace / f'artifacts/system-hardware-followup-sheng-r{revision}'
        parent = json.loads((directory / 'build-result.json').read_text())
        assert parent['revision'] == revision and parent['complete_avb_chain_verified']
        assert parent['all_filesystem_stages_verified'] and parent['original_systemui_unchanged']
        for entry in parent['files']:
            path = directory / entry['name']
            assert path.stat().st_size == entry['bytes'] and sha(path) == entry['sha256']
            chain_inputs[entry['partition']] = path
    assert sha(chain_inputs['system_ext']) == 'd9d2ed50e17169c927f51dcd4d6fd414a9a7e5b728da36b2069ca0306ab95bcd'
    output_scope = {*SCOPE, 'vbmeta', 'vbmeta_system'}
    baseline = {part: sha(chain_inputs[part]) for part in output_scope}
    destination = workspace / 'artifacts/system-hardware-followup-sheng-r42'
    assert not destination.exists()
    # Disk work avoids exhausting tmpfs while two large metadata-preserving EROFS
    # readbacks coexist. Keep the directory as reproducible diagnostic evidence.
    work = Path(tempfile.mkdtemp(prefix='r42-package-', dir='/root/sheng-lineage/hardware-diagnostics'))
    assert shutil.disk_usage(work).free > 15 * 1024**3
    sys.path.insert(0, str(ROM / 'external/avb'))
    import avbtool
    avb = avbtool.Avb()
    reference = work / 'original-SystemUI.apk'
    debugfs(chain_inputs['system_ext'], f'dump /priv-app/SystemUI/SystemUI.apk {reference}')
    assert sha(reference) == '33017b0d59e28da5db3e089a98f49601de508228a012392ee2d04c82cda3ccb1'
    nodes = {relative: dict(uid=0, gid=0, mode=0o755 if relative == 'priv-app/ShengFaceUnlock' else 0o644,
                           mtime_ns=1230768000 * 1_000_000_000, selinux='u:object_r:system_file:s0')
             for relative in {*SCOPE['system_ext'], 'priv-app/ShengFaceUnlock'}}
    outputs, trees, reports = {}, {}, {}
    print('Adding FaceUnlock with explicit new-node metadata', flush=True)
    outputs['system_ext'], trees['system_ext'], reports['system_ext'] = stage_ext4(
        'system_ext', chain_inputs['system_ext'], entries['system_ext'], nodes, work,
        avb, avbtool, certificates(reference))
    for part in ('odm', 'vendor'):
        print('Retiring legacy face payloads in ' + part, flush=True)
        outputs[part], trees[part], reports[part] = stage_erofs(
            part, chain_inputs[part], entries[part], {}, work, avb, avbtool)
    for part in SCOPE:
        assert set(reports[part]['changed_files']) == SCOPE[part]
        assert reports[part]['metadata_preserved']
    outputs['vbmeta_system'] = work / 'vbmeta_system.img'
    merge_parent(avb, avbtool, chain_inputs['vbmeta_system'], [trees['system_ext']],
                 outputs['vbmeta_system'], 'SHA256_RSA2048', work)
    outputs['vbmeta'] = work / 'vbmeta.img'
    merge_parent(avb, avbtool, chain_inputs['vbmeta'], [trees['odm'], trees['vendor']],
                 outputs['vbmeta'], 'SHA256_RSA4096', work)
    chain = work / 'complete-chain'; chain.mkdir()
    for part, path in chain_inputs.items(): (chain / (part + '.img')).symlink_to(outputs.get(part, path).resolve())
    result = subprocess.run([HOST / 'avbtool', 'verify_image', '--image', chain / 'vbmeta.img',
                             '--follow_chain_partitions'], capture_output=True, text=True)
    (work / 'complete-chain.avb.txt').write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    for relative, expected in review['sources_sha256'].items(): assert sha(workspace / relative) == expected, relative
    for part in SCOPE: validate_inputs(part, entries[part])
    assert {part: sha(chain_inputs[part]) for part in output_scope} == baseline
    evidence = workspace / 'reports/device/20261110-resume/face-system/r42-package'
    evidence.mkdir(exist_ok=False)
    for path in work.iterdir():
        if path.is_file() and path.suffix in ('.log', '.txt', '.json'): shutil.copyfile(path, evidence / path.name)
    publish_batch(destination, outputs, dict(revision=42, baseline_sha256=baseline,
        build_review_sha256=sha(args.build_review), post_audit_sha256=sha(args.post_audit),
        source_commit=subprocess.check_output(['git', '-C', workspace, 'rev-parse', 'HEAD'], text=True).strip(),
        entries=entries, partition_reports=reports, all_filesystem_stages_verified=True,
        complete_avb_chain_verified=True, original_systemui_unchanged=True,
        normal_module_build_passed=True, full_product_build_passed=False,
        api1_runtime_tested=False, hardware_boot_tested=False, lockscreen_unlock_tested=False,
        persistent_build_evidence_dir=str(evidence), work_dir=str(work)))
    print(destination, flush=True)


if __name__ == '__main__': main()
