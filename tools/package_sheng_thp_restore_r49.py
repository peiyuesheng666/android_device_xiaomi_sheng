#!/usr/bin/env python3
"""Withdraw the measured-ineffective THP profile over the verified r48 batch."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys

from package_sheng_batch_helpers import (erofs_input_keys, merge_parent,
    packaging_input_path, publish_batch, stage_erofs, validate_inputs,
    validate_packaging_inputs)
from package_sheng_model_followup import HOST, PRODUCT, ROM, sha

ORIGINAL = 'cb75e8cf9128f9ea6177d8276d440dc16f55db8f068f7644e94668cfc8f6e2c5'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'build-log', 'audit', 'mirror', 'work']:
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve(strict=True)
    args.work.mkdir(exist_ok=False)
    work = args.work
    assert shutil.disk_usage(work).free > 5 * 1024**3
    assert '#### build completed successfully' in args.build_log.read_text()
    audit = json.loads(args.audit.read_text())
    mirror = json.loads(args.mirror.read_text())
    assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
    assert datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(audit['date_utc']).timestamp() < 7200
    assert mirror['passed'] and 'device.mk' in mirror['scopes']
    def check_sources():
        for name, entry in mirror['inputs'].items():
            assert entry['kind'] == 'file' and sha(workspace/name) == sha(ROM/name) == entry['sha256']
    check_sources()
    previous = json.loads((workspace/'artifacts/system-hardware-followup-sheng-r48/build-result.json').read_text())
    assert previous['complete_avb_chain_verified'] and previous['original_systemui_unchanged']
    assert previous['boot_policy']['actual_partition_neverallows_passed']
    assert previous['vintf']['actual_partition_combination_compatible']
    digests = {e['partition']:e['sha256'] for e in json.loads(
        (workspace/'reports/device/r38-restore-20261110/restore-manifest.json').read_text())['files']}
    for revision in [39,40,41,42,44,45,48]:
        report = json.loads((workspace/f'artifacts/system-hardware-followup-sheng-r{revision}/build-result.json').read_text())
        for entry in report['files']:
            digests[entry['partition']] = entry['sha256']
    cache = Path('/root/sheng-lineage/hardware-diagnostics/sheng-bt-touch-r48-20261111/package6/complete-chain')
    chain = {part:cache/(part+'.img') for part in digests}
    assert all(sha(path) == digests[part] for part,path in chain.items())
    relative = 'firmware/n81a_nova_thp_config.ini'
    source = PRODUCT/'odm'/relative
    assert sha(source) == ORIGINAL == sha(workspace/'reports/device/20261111-simple/thp-config-before.ini')
    assert source.read_bytes() == (ROM/'vendor/xiaomi/sheng/proprietary/odm'/relative).read_bytes()
    entries = {'odm':{relative:dict(source=str(source),kind='file',bytes=source.stat().st_size,sha256=ORIGINAL)}}
    validate_inputs('odm',entries['odm'])
    frozen = {key:sha(packaging_input_path(key)) for key in erofs_input_keys('odm')}
    validate_packaging_inputs(entries,frozen)
    sys.path.insert(0,str(ROM/'external/avb'))
    import avbtool
    avb = avbtool.Avb()
    image, tree, report = stage_erofs('odm',chain['odm'],entries['odm'],{},work,avb,avbtool)
    assert report['metadata_preserved'] and set(report['changed_files']) == {relative}
    outputs = {'odm':image,'vbmeta':work/'vbmeta.img'}
    merge_parent(avb,avbtool,chain['vbmeta'],[tree],outputs['vbmeta'],'SHA256_RSA4096',work)
    complete = work/'complete-chain'
    complete.mkdir()
    for part,path in chain.items():
        (complete/(part+'.img')).symlink_to(outputs.get(part,path).resolve())
    result = subprocess.run([HOST/'avbtool','verify_image','--image',complete/'vbmeta.img','--follow_chain_partitions'],
                            text=True,capture_output=True)
    (work/'complete-chain.avb.log').write_text(result.stdout+result.stderr)
    assert result.returncode == 0,result.stdout+result.stderr
    merged_entries = {part:dict(value) for part,value in previous['entries'].items()}
    merged_entries['odm'].update(entries['odm'])
    for part,value in merged_entries.items():
        validate_inputs(part,value)
    validate_packaging_inputs(entries,frozen)
    check_sources()
    publish_batch(workspace/'artifacts/system-hardware-followup-sheng-r49',outputs,dict(
        revision=49,baseline_revision=48,baseline_sha256={part:digests[part] for part in ['odm','product','system_ext','vendor','vbmeta','vbmeta_system']},
        unchanged_partition_files=[e for e in previous['files'] if e['partition'] not in outputs],
        entries=merged_entries,partition_reports={'odm':report},
        original_thp_restored=True,original_thp_sha256=ORIGINAL,
        policy_unchanged_from_strict_r48=True,vintf_unchanged_from_verified_r48=True,
        original_systemui_unchanged=True,complete_avb_chain_verified=True,
        all_filesystem_stages_verified=True,normal_module_build_passed=True,
        full_product_build_passed=False,physical_sampling_increase_tested=True,high_sampling_fixed=False,
        sources_sha256={name:e['sha256'] for name,e in mirror['inputs'].items()},
        build_log_sha256=sha(args.build_log),post_audit_sha256=sha(args.audit),source_mirror_sha256=sha(args.mirror),
        packaging_inputs=frozen,work_dir=str(work),hardware_boot_tested=False,
        source_commit=subprocess.check_output(['git','-C',workspace,'rev-parse','HEAD'],text=True).strip()))
    print(workspace/'artifacts/system-hardware-followup-sheng-r49',flush=True)


if __name__ == '__main__':
    main()
