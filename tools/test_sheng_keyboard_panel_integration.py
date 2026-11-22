#!/usr/bin/env python3
"""Replay the keyboard panel fix and Android source pins on isolated source copies."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tempfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv, cwd, env=None):
    result = subprocess.run(list(map(str, argv)), cwd=cwd, env=env,
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f'{argv}:\n{result.stdout}{result.stderr}')
    return result.stdout.strip()


def patch_paths(patch):
    return set(re.findall(r'^--- a/(.+)$', patch.read_text(), re.MULTILINE))


def verify(source, project):
    device = Path(__file__).resolve().parents[1]
    overlays = device / 'interfaces/kernel/6.18'
    panel_patch = overlays / 'patches/0038-keyboard-panel-state.patch'
    readiness_patch = overlays / 'patches/0039-keyboard-boot-readiness.patch'
    caps_patch = overlays / 'patches/0040-keyboard-sleep-caps.patch'
    source_patches = (panel_patch, readiness_patch, caps_patch)
    module_patches = sorted((overlays / 'android-module-patches').glob('*.patch'))
    contract = 'scripts/android_source_contract.py'
    baseline = runpy.run_path(str(project / contract))['EXPECTED']
    # Use a known, fully prepared pre-panel baseline; do not manufacture missing inputs.
    for name, expected in baseline.items():
        assert sha(source / name) == expected, 'Pinned baseline differs: ' + name
    tools = device / 'tools'
    dp_inputs = {'k618/' + name for name in runpy.run_path(str(tools / 'prepare_sheng_dp_usb.py'))['CHANGES']}
    wlan_input = 'k618/' + str(runpy.run_path(str(tools / 'prepare_sheng_wlan_response.py'))['RELATIVE'])
    usb_inputs = {'k618/soc/drivers/usb/dwc3/dwc3-msm-core.c'}
    touched = set(baseline) | dp_inputs | usb_inputs | {wlan_input}
    before_files = {name: sha(source / name) for name in touched.union(*(patch_paths(patch) for patch in source_patches))}
    with tempfile.TemporaryDirectory(prefix='sheng-keyboard-panel-replay-') as directory:
        root = Path(directory)
        build, copied_project = root / 'build', root / 'project'
        build.mkdir()
        copied_project.mkdir()
        for name in before_files:
            destination = build / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, destination)
        targets = {contract, 'scripts/android_lts_contract.py'}
        targets.update(name for patch in module_patches for name in patch_paths(patch))
        for name in targets:
            destination = copied_project / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(project / name, destination)
        for patch in module_patches:
            run(['git', 'apply', '--check', patch], copied_project)
            run(['git', 'apply', patch], copied_project)
            run(['git', 'apply', '--reverse', '--check', patch], copied_project)
        for patch in source_patches:
            run(['git', 'apply', '--check', patch], build)
            run(['git', 'apply', patch], build)
            run(['git', 'apply', '--reverse', '--check', patch], build)
        packet = 'k618/sheng-ports/keyboard/sheng_nanosic_panel.h'
        assert (build / packet).read_bytes() == (overlays / 'helpers/sheng_nanosic_panel.h').read_bytes()
        for helper in ('prepare_sheng_dp_usb.py', 'prepare_sheng_charge_error_contract.py',
                       'prepare_sheng_wlan_response.py'):
            run([sys.executable, tools / helper, '--source-root', build / 'k618'], build)
        env = dict(os.environ, BUILD_ROOT=str(build), PYTHONDONTWRITEBYTECODE='1')
        run([sys.executable, copied_project / contract, '--apply-sheng-usb3'], copied_project, env)
        success = run([sys.executable, copied_project / contract], copied_project, env)
        final = runpy.run_path(str(copied_project / contract))['EXPECTED']
        for name, expected in final.items():
            assert sha(build / name) == expected, name
        # A partial/mutated panel implementation must still fail the production pins.
        header = build / packet
        original = header.read_bytes()
        header.write_bytes(original.replace(b'0x5d', b'0x5c', 1))
        rejected = subprocess.run([sys.executable, copied_project / contract],
                                  cwd=copied_project, env=env, capture_output=True).returncode != 0
        assert rejected, 'Source contract accepted an incorrect sleep command'
        header.write_bytes(original)
        run([sys.executable, copied_project / contract], copied_project, env)
        result = dict(passed=True, baseline_pinned_files=len(baseline), final_pinned_files=len(final),
                      module_patches_replayed=[p.name for p in module_patches],
                      source_patch_replayed=panel_patch.name,
                      source_patch_sha256=sha(panel_patch),
                      readiness_patch_sha256=sha(readiness_patch),
                      module_patch_sha256={p.name: sha(p) for p in module_patches},
                      final_source_sha256=final, helper_matches_replayed_header=True,
                      incorrect_sleep_command_rejected=rejected,
                      production_source_contract_output=success)
    assert all(sha(source / name) == expected for name, expected in before_files.items())
    result.update(original_sources_unchanged=True, temporary_copies_removed=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path, help='Prepared root containing k618')
    parser.add_argument('--project-root', required=True, type=Path, help='Unpatched Android kernel build project')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = verify(args.source_root.resolve(), args.project_root.resolve())
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'final_source_sha256'}, indent=2))
