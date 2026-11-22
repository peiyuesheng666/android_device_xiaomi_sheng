#!/usr/bin/env python3
"""Seal keyboard attachment/fold policy over the installed r52 partition chain."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
from package_sheng_batch_helpers import (certificates, debugfs, merge_parent, publish_batch,
    stage_erofs, stage_ext4, validate_inputs, verify_boot_policy)
from package_sheng_model_followup import HOST, PRODUCT, ROM, sha

UI_HASH = '33017b0d59e28da5db3e089a98f49601de508228a012392ee2d04c82cda3ccb1'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'build-log', 'audit', 'mirror', 'work']:
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve(strict=True)
    work = args.work
    work.mkdir(exist_ok=False)
    assert shutil.disk_usage(work).free > 6*1024**3
    assert '#### build completed successfully' in args.build_log.read_text()
    assert (HOST/'soong_build').read_bytes()[:4] == b'\x7fELF'
    audit, mirror = [json.loads(p.read_text()) for p in [args.audit, args.mirror]]
    assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
    assert datetime.now(timezone.utc).timestamp()-datetime.fromisoformat(audit['date_utc']).timestamp() < 7200
    assert mirror['passed'] and mirror['scopes'] == ['BoardConfig.mk', 'interfaces/input/keyboard']
    def sources():
        for name, entry in mirror['inputs'].items():
            assert entry['kind'] == 'file' and sha(workspace/name) == sha(ROM/name) == entry['sha256'], name
    sources()
    previous = json.loads((workspace/'artifacts/system-hardware-followup-sheng-r52/build-result.json').read_text())
    assert previous['complete_avb_chain_verified'] and previous['original_systemui_unchanged']
    files = previous['files'] + previous['unchanged_partition_files']
    digests = {e['partition']: e['sha256'] for e in files}
    chain = {p: Path(previous['work_dir'])/'complete-chain'/(p+'.img') for p in digests}
    assert all(sha(path) == digests[p] for p, path in chain.items())
    system_receipt = next(e for e in json.loads((workspace/'reports/device/r38-restore-20261110/restore-manifest.json').read_text())['files']
        if e['partition'] == 'system')
    chain['system'] = Path(previous['work_dir'])/'complete-chain/system.img'
    assert sha(chain['system']) == system_receipt['sha256']
    # Retain the immutable boot/module dependencies from r52's verified chain.
    # They participate in AVB verification even though this update never flashes them.
    for path in (Path(previous['work_dir'])/'complete-chain').glob('*.img'):
        if path.stem not in chain: chain[path.stem] = path
    boot_dependencies = [dict(partition=p, bytes=path.stat().st_size, sha256=sha(path))
        for p, path in chain.items() if p not in digests and p != 'system']
    commands = []
    def run(argv):
        value = subprocess.run(list(map(str, argv)), text=True, capture_output=True)
        commands.append(dict(argv=list(map(str, argv)), returncode=value.returncode,
            stdout=value.stdout, stderr=value.stderr))
        (work/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
        assert value.returncode == 0, value.stdout+value.stderr
        return value.stdout
    ref = work/'SystemUI-reference.apk'
    debugfs(chain['system_ext'], f'dump /priv-app/SystemUI/SystemUI.apk {ref}')
    assert sha(ref) == UI_HASH
    apk = PRODUCT/'system_ext/priv-app/ShengKeyboardPresence/ShengKeyboardPresence.apk'
    run([HOST/'apksigner', 'verify', apk])
    run([HOST/'zipalign', '-c', '-P', '16', '4', apk])
    assert certificates(apk) == certificates(ref)
    manifest = run([HOST/'aapt2', 'dump', 'xmltree', apk, '--file', 'AndroidManifest.xml'])
    assert all(name in manifest for name in ['org.lineageos.sheng.keyboard', 'DISABLE_INPUT_DEVICE',
        'TABLET_MODE', 'persistent', 'directBootAware'])
    assert not any(name in manifest for name in ['CAMERA', 'E: activity', 'E: service'])
    run([HOST/'fsck.erofs', '-d0', '--extract='+str(work/'baseline-vendor'), '--preserve', chain['vendor']])
    before = (work/'baseline-vendor/etc/selinux/vendor_sepolicy.cil').read_text().splitlines()
    after = (PRODUCT/'vendor/etc/selinux/vendor_sepolicy.cil').read_text().splitlines()
    delta = set(before) ^ set(after)
    (work/'policy-delta.json').write_text(json.dumps(sorted(delta), indent=2)+'\n')
    def normalized(lines):
        result = set()
        for line in lines:
            if not line.strip() or line.lstrip().startswith(';'): continue
            if 'sysfs_sheng_keyboard_state' in line:
                if line.startswith('(typeattributeset '):
                    line = line.replace(' sysfs_sheng_keyboard_state', '')
                else: continue
            result.add(line)
        return result
    assert delta and normalized(before) == normalized(after), 'Unrelated vendor policy drift'
    added_rules = [line for line in set(after)-set(before) if line.startswith('(allow ')]
    assert len(added_rules) == 2 and all('sysfs_sheng_keyboard_state' in line for line in added_rules)
    for path in ['etc/selinux/system_ext_sepolicy.cil', 'etc/selinux/system_ext_sepolicy_and_mapping.sha256']:
        dumped = work/Path(path).name
        debugfs(chain['system_ext'], f'dump /{path} {dumped}')
        assert sha(dumped) == sha(PRODUCT/'system_ext'/path), 'Unrelated system_ext policy drift: '+path
    scope = {'system_ext': ['priv-app/ShengKeyboardPresence/ShengKeyboardPresence.apk',
        'etc/init/init.sheng-keyboard-presence.rc'], 'vendor': ['etc/selinux/vendor_sepolicy.cil']}
    entries = {p: {name: dict(source=str(PRODUCT/p/name), kind='file', bytes=(PRODUCT/p/name).stat().st_size,
        sha256=sha(PRODUCT/p/name)) for name in names} for p, names in scope.items()}
    for p, values in entries.items(): validate_inputs(p, values)
    stamp = 1230768048*1_000_000_000
    nodes = {name: dict(uid=0, gid=0, mode=mode, mtime_ns=stamp, selinux='u:object_r:system_file:s0')
        for name, mode in [('priv-app/ShengKeyboardPresence', 0o755),
        ('priv-app/ShengKeyboardPresence/ShengKeyboardPresence.apk', 0o644),
        ('etc/init/init.sheng-keyboard-presence.rc', 0o644)]}
    sys.path.insert(0, str(ROM/'external/avb'))
    import avbtool
    avb = avbtool.Avb()
    outputs, trees, reports = {}, {}, {}
    print('Staging keyboard system_ext and vendor policy', flush=True)
    outputs['system_ext'], trees['system_ext'], reports['system_ext'] = stage_ext4(
        'system_ext', chain['system_ext'], entries['system_ext'], nodes, work, avb, avbtool, certificates(ref))
    outputs['vendor'], trees['vendor'], reports['vendor'] = stage_erofs(
        'vendor', chain['vendor'], entries['vendor'], {}, work, avb, avbtool)
    assert sha(work/'system_ext-after/priv-app/SystemUI/SystemUI.apk') == UI_HASH
    assert sha(work/'vendor-tree/build.prop') == sha(work/'baseline-vendor/build.prop')
    assert reports['system_ext']['metadata_preserved'] and reports['vendor']['metadata_preserved']
    assert set(reports['system_ext']['changed_files']) == set(scope['system_ext'])
    assert reports['vendor']['changed_files'] == scope['vendor']
    run([HOST/'fsck.erofs', '-d0', '--extract='+str(work/'odm-tree'), '--preserve', chain['odm']])
    boot_policy = verify_boot_policy({**chain, **outputs}, work)
    # Existing helpers already enforce neverallows, but retain an explicit strict compile receipt.
    selected = [work/name for name in boot_policy['input_sha256']]
    run([HOST/'secilc', selected[0], '-m', '-M', 'true', '-G', '-c', '30', selected[1],
        '-o', work/'combined-policy-strict', '-f', '/dev/null', *selected[2:]])
    for part, algorithm, child in [('vbmeta_system', 'SHA256_RSA2048', 'system_ext'),
        ('vbmeta', 'SHA256_RSA4096', 'vendor')]:
        outputs[part] = work/(part+'.img')
        merge_parent(avb, avbtool, chain[part], [trees[child]], outputs[part], algorithm, work)
    complete = work/'complete-chain'
    complete.mkdir()
    for part, path in chain.items(): (complete/(part+'.img')).symlink_to(outputs.get(part, path).resolve())
    run([HOST/'avbtool', 'verify_image', '--image', complete/'vbmeta.img', '--follow_chain_partitions'])
    sources()
    for p, values in entries.items(): validate_inputs(p, values)
    unchanged = [dict(partition=p, name=p+'.img', bytes=path.stat().st_size, sha256=digests[p])
        for p, path in chain.items() if p not in outputs and p in digests]
    publish_batch(workspace/'artifacts/system-hardware-followup-sheng-r53', outputs, dict(
        revision=53, baseline_revision=52, baseline_sha256=digests, unchanged_partition_files=unchanged,
        unchanged_boot_dependencies=boot_dependencies,
        entries=entries, partition_reports=reports, boot_policy=boot_policy,
        original_systemui_unchanged=True, complete_avb_chain_verified=True, all_filesystem_stages_verified=True,
        normal_module_build_passed=True, full_product_build_passed=False, hardware_boot_tested=False,
        keyboard_physical_presence_integrated=True, keyboard_tablet_mode_integrated=True,
        keyboard_endpoints=['15d9:00a1', '15d9:00a2', '15d9:00a3', '15d9:00a4'],
        touch_r50_retained=True, dolby_ui_r51_retained=True, dolby_media_r52_retained=True,
        pen_fixed=False, vintf_unchanged=True, candidate_dolby_r53_installed=False,
        sources_sha256={n: e['sha256'] for n, e in mirror['inputs'].items()},
        build_log_sha256=sha(args.build_log), source_mirror_sha256=sha(args.mirror), post_audit_sha256=sha(args.audit),
        work_dir=str(work), source_commit=subprocess.check_output(['git', '-C', workspace, 'rev-parse', 'HEAD'], text=True).strip()))
    print('Published accessory r53', flush=True)

if __name__ == '__main__': main()
