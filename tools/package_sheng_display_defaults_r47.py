#!/usr/bin/env python3
"""Review and seal the display-defaults batch over the installed r45 chain."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from package_sheng_batch_helpers import (certificates, debugfs, erofs_input_keys,
    merge_parent, packaging_input_path, publish_batch, stage_erofs, stage_ext4,
    validate_inputs, validate_packaging_inputs)
from package_sheng_model_followup import HOST, PRODUCT, ROM, sha

SCOPE = {
    'odm': ['overlay/FrameworkResOverlaySheng.apk', 'overlay/LineageResOverlaySheng.apk'],
    'system_ext': ['priv-app/ShengDisplayDefaults/ShengDisplayDefaults.apk'],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--build-log', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--mirror', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    assert __debug__
    workspace = args.workspace.resolve(strict=True)
    args.work.mkdir(exist_ok=False)
    work = args.work
    assert shutil.disk_usage(work).free > 20 * 1024**3
    assert '#### build completed successfully' in args.build_log.read_text()
    assert (ROM/'out/host/linux-x86/bin/soong_build').read_bytes()[:4] == b'\x7fELF'
    audit, mirror = json.loads(args.audit.read_text()), json.loads(args.mirror.read_text())
    assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
    assert datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(audit['date_utc']).timestamp() < 7200
    assert mirror['passed'] and set(mirror['scopes']) == {
        'interfaces/display/defaults', 'overlay/FrameworkResOverlaySheng', 'overlay/LineageResOverlaySheng'}
    for name, expected in mirror['inputs'].items():
        assert expected['kind'] == 'file'
        assert sha(workspace/name) == sha(ROM/name) == expected['sha256'], name
    commands = []
    def run(argv):
        result = subprocess.run(list(map(str, argv)), capture_output=True, text=True)
        commands.append(dict(argv=list(map(str, argv)), returncode=result.returncode,
                             stdout=result.stdout, stderr=result.stderr))
        (work/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout
    entries = {}
    for part, paths in SCOPE.items():
        entries[part] = {}
        for relative in paths:
            source = PRODUCT/part/relative
            entries[part][relative] = dict(source=str(source), kind='file',
                bytes=source.stat().st_size, sha256=sha(source))
            run([HOST/'zipalign', '-c', '-P', '16', '4', source])
        validate_inputs(part, entries[part])
    for name, target in [('FrameworkResOverlaySheng', 'framework-res.apk'),
                         ('LineageResOverlaySheng', 'org.lineageos.platform-res.apk')]:
        apk = PRODUCT/'odm/overlay'/(name+'.apk')
        resources = run([HOST/'aapt2', 'dump', 'resources', apk])
        (work/(name+'.resources.txt')).write_text(resources)
        required = (['config_defaultRefreshRate', 'config_defaultPeakRefreshRate']
                    if name == 'FrameworkResOverlaySheng' else
                    ['config_buttonBrightnessSettingDefaultFloat', 'config_keyboardBrightnessSettingDefaultFloat'])
        for key in required:
            value = re.search(r'(?m)^\s*resource [^\n]*\b'+key+r'\b[^\n]*\n([^\n]*)', resources)
            assert value, key
            assert float(value[1].strip().split()[-1]) == (144 if name == 'FrameworkResOverlaySheng' else 0), value[0]
        run([HOST/'idmap2', 'create', '--target-apk-path', PRODUCT/'system/framework'/target,
             '--overlay-apk-path', apk, '--idmap-path', work/(name+'.idmap'),
             '--policy', 'public', '--policy', 'odm', '--policy', 'signature'])
    manifest = run([HOST/'aapt2', 'dump', 'badging', PRODUCT/'system_ext'/SCOPE['system_ext'][0]])
    assert "versionCode='2'" in manifest and "versionName='1.1'" in manifest
    chain, digests = {}, {}
    restored = json.loads((workspace/'reports/device/r38-restore-20261110/restore-manifest.json').read_text())
    assert restored['complete_avb_chain_verified']
    for entry in restored['files']:
        chain[entry['partition']] = workspace/entry['path']
        digests[entry['partition']] = entry['sha256']
        assert chain[entry['partition']].stat().st_size == entry['bytes']
    manifests = {}
    for revision in [39, 40, 41, 42, 44, 45]:
        directory = workspace/f'artifacts/system-hardware-followup-sheng-r{revision}'
        previous = json.loads((directory/'build-result.json').read_text())
        manifests[revision] = previous
        assert previous['complete_avb_chain_verified'] and previous['all_filesystem_stages_verified']
        assert previous['original_systemui_unchanged']
        for entry in previous['files']:
            path = directory/entry['name']
            assert path.stat().st_size == entry['bytes']
            chain[entry['partition']], digests[entry['partition']] = path, entry['sha256']
    # Hash/cache the exact final baseline locally before reading AVB blocks.
    cached = {}
    for part, path in chain.items():
        assert sha(path) == digests[part], part
        target = work/f'base-{part}.img'
        shutil.copyfile(path, target)
        assert sha(target) == digests[part]
        cached[part] = target
    chain = cached
    parent = manifests[44]
    assert parent['boot_policy']['actual_partition_combination_compiled']
    assert parent['vintf']['actual_partition_combination_compatible']
    reference = work/'original-SystemUI.apk'
    debugfs(chain['system_ext'], f'dump /priv-app/SystemUI/SystemUI.apk {reference}')
    assert sha(reference) == '33017b0d59e28da5db3e089a98f49601de508228a012392ee2d04c82cda3ccb1'
    frozen = {name: sha(packaging_input_path(name)) for name in erofs_input_keys('odm')}
    validate_packaging_inputs(SCOPE, frozen)
    sys.path.insert(0, str(ROM/'external/avb'))
    import avbtool
    avb = avbtool.Avb()
    outputs, trees, reports = {}, {}, {}
    for part in SCOPE:
        print('Staging '+part, flush=True)
        common = part, chain[part], entries[part], {}, work, avb, avbtool
        image, tree, report = (stage_erofs(*common) if part == 'odm' else
            stage_ext4(*common, certificates(reference),
                replacement_mtimes={SCOPE['system_ext'][0]:1230768047}))
        assert report['metadata_preserved']
        assert set(report['changed_files']) <= set(SCOPE[part])
        outputs[part], trees[part], reports[part] = image, tree, report
    for part, algorithm in [('vbmeta', 'SHA256_RSA4096'), ('vbmeta_system', 'SHA256_RSA2048')]:
        outputs[part] = work/(part+'.img')
        merge_parent(avb, avbtool, chain[part], [trees['odm' if part == 'vbmeta' else 'system_ext']],
                     outputs[part], algorithm, work)
    complete = work/'complete-chain'
    complete.mkdir()
    for part, path in chain.items():
        (complete/(part+'.img')).symlink_to(outputs.get(part, path).resolve())
    run([HOST/'avbtool', 'verify_image', '--image', complete/'vbmeta.img', '--follow_chain_partitions'])
    for part in SCOPE:
        validate_inputs(part, entries[part])
    validate_packaging_inputs(SCOPE, frozen)
    for name, expected in mirror['inputs'].items():
        assert sha(workspace/name) == sha(ROM/name) == expected['sha256'], name
    destination = workspace/'artifacts/system-hardware-followup-sheng-r47'
    publish_batch(destination, outputs, dict(revision=47, baseline_sha256={part:digests[part] for part in outputs},
        entries=entries, sources_sha256={name:value['sha256'] for name,value in mirror['inputs'].items()},
        build_log_sha256=sha(args.build_log), post_audit_sha256=sha(args.audit), source_mirror_sha256=sha(args.mirror),
        partition_reports=reports, packaging_inputs=frozen, boot_policy=parent['boot_policy'], vintf=parent['vintf'],
        policy_and_vintf_unchanged_from_r45=True, all_filesystem_stages_verified=True,
        complete_avb_chain_verified=True, original_systemui_unchanged=True, normal_module_build_passed=True,
        first_setup_seed_144=True, full_product_build_passed=False, hardware_boot_tested=False,
        face_r46_installed=False, work_dir=str(work),
        source_commit=subprocess.check_output(['git','-C',str(workspace),'rev-parse','HEAD'],text=True).strip()))
    print(destination, flush=True)


if __name__ == '__main__':
    main()
