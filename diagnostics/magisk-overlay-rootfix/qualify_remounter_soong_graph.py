#!/usr/bin/env python3
"""Generate an official target-closure Soong graph without compiling/installing.

Uses the retained custom_sheng userdebug variables and complete module list.
This is not full-product graph/Make installation or Android runtime acceptance.
Does not alter public sources, retained graphs, device partitions, or swap.
"""
import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from storage_guard import require_build_space

HOST_FLOOR_BYTES = 6 * 1024**3
# The terminated 20261120j attempt produced 4.9 GiB of graph/metadata alone.
# Reserve growth BEFORE starting, rather than merely checking the stop floor.
# This is planning headroom, not a guarantee of total build size.
GRAPH_GROWTH_RESERVE_BYTES = 8 * 1024**3


def require_analysis_space(work, report):
    checks = require_build_space(
        work, minimum_output=GRAPH_GROWTH_RESERVE_BYTES,
        minimum_host=HOST_FLOOR_BYTES + GRAPH_GROWTH_RESERVE_BYTES)
    require_build_space(report, minimum_output=64 * 1024**2,
                        minimum_host=HOST_FLOOR_BYTES + GRAPH_GROWTH_RESERVE_BYTES)
    return checks


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relocate_testcase_outputs(variables, old_output, new_output):
    # These generated paths must remain children of this analysis's output;
    # keeping old values causes Soong's path containment checks to reject them.
    # Do not alter tool PATHs or any architecture/policy/module configuration.
    result = copy.deepcopy(variables)
    count = 0
    for value in result.get('CompatibilityTestcases', {}).values():
        old = Path(value['OutDir'])
        relative = old.relative_to(old_output)
        if '..' in relative.parts:
            raise ValueError('Unsafe testcase output')
        value['OutDir'] = str(Path(new_output) / relative)
        count += 1
    return result, count


def discover_blueprints(root):
    """Match the source finder's no-directory-symlinks/prune-marker policy."""
    result = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        if '.out-dir' in files or '.find-ignore' in files:
            dirs[:] = []
            continue
        dirs[:] = [name for name in dirs if name not in ('.git', '.repo')
                   and not (Path(directory) / name).is_symlink()]
        if 'Android.bp' in files:
            result.append(str((Path(directory) / 'Android.bp').relative_to(root)))
    return sorted(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--product-config', type=Path,
                        help='Native output from actual current soong_ui --config-only')
    parser.add_argument('--source-variants', action='store_true',
                        help='Analyze owned first-stage/fs_mgr/snapshot and remounter targets together')
    args = parser.parse_args()
    rom = args.rom.resolve(strict=True)
    workspace = args.workspace.resolve(strict=True)
    work, report = args.work.resolve(), args.report.resolve()
    # All generated native build output remains in this C-backed ROM tree.
    relative_work = work.relative_to(rom)
    assert len(relative_work.parts) == 1 and relative_work.name.startswith('out-sheng-remounter-soong-')
    assert not work.exists() and not report.exists(), 'Never overwrite earlier evidence'
    retained = rom / 'out-clean-ota-20261116'
    product_config = args.product_config.resolve(strict=True) if args.product_config else retained
    assert product_config.parent == rom, 'Product configuration must remain native'
    builder = retained / 'host/linux-x86/bin/soong_build'
    assert not builder.with_name('soong_build.sheng-real').exists(), 'Analyzer wrapper owned elsewhere'
    storage = require_analysis_space(work, report)
    public = [rom / 'system/fs/fs_mgr/Android.bp',
              rom / 'system/fs/fs_mgr/fs_mgr_overlayfs_mount.cpp',
              rom / 'system/core/init/Android.bp',
              rom / 'system/core/overlay_remounter/overlay_remounter.cpp']
    owned = Path('device/xiaomi/sheng/interfaces/compat/overlay-remounter')
    source_paths = ['Android.bp', 'overlay_remounter.cpp', 'mount_preserver.h', 'product.mk']
    assert not (rom / owned / 'Android.mk').exists(), 'Remove obsolete experimental Make installer'
    assert not (workspace / owned / 'Android.mk').exists(), 'Obsolete workspace Make installer'
    for name in source_paths:
        assert sha(rom / owned / name) == sha(workspace / owned / name), 'Source mirror drift: ' + name
    inputs = [builder, product_config / 'soong/soong.custom_sheng.variables',
              retained / '.module_paths/Android.bp.list',
              retained / 'soong/soong.environment.available', *public,
              *(rom / owned / name for name in source_paths)]
    targets = ['sheng_overlay_remounter', 'overlay_remounter', 'prebuilt_overlay_remounter']
    if args.source_variants:
        targets += ['sheng_init_first_stage', 'prebuilt_init_first_stage', 'libsheng_fs_mgr_first_stage',
                    'libsheng_snapshot_init', 'init_first_stage']
        for module in ('first-stage-init', 'fs-mgr-first-stage', 'snapshot-first-stage',
                       'first-stage-crypto', 'first-stage-unwind', 'first-stage-zstd'):
            relative = Path('device/xiaomi/sheng/interfaces/compat') / module
            for path in (workspace / relative).rglob('*'):
                if path.is_file() and (path.suffix in ('.c', '.cc', '.cpp', '.h', '.bp', '.mk',
                                                       '.S', '.s', '.inc', '.asm', '.pl', '.map', '.lds')
                                       or path.name.startswith(('NOTICE', 'LICENSE', 'COPYING', 'BIONIC_NOTICE'))):
                    native = rom / path.relative_to(workspace)
                    assert sha(native) == sha(path), 'Source mirror drift: ' + str(path)
                    inputs.append(native)
    available = {item['Key']: item['Value'] for item in json.loads(inputs[3].read_text())}
    date_relative = (rom / available['BUILD_DATETIME_FILE']).relative_to(retained)
    date_source = product_config / date_relative
    assert '..' not in date_relative.parts
    inputs.append(date_source)
    before = {str(path): sha(path) for path in inputs}
    variables = json.loads(inputs[1].read_text())
    assert variables['Debuggable'] and variables['DeviceProduct'] == 'custom_sheng'
    assert not variables.get('Allow_missing_dependencies', False)
    assert variables.get('VendorVars', {}).get('sheng', {}).get('first_stage_rootfix') == 'true', \
        'Generate actual current debug product config; do not inject VendorVars by hand'
    inherited = json.loads((retained / 'soong/soong.custom_sheng.variables').read_text())
    assert set(inherited.get('NamespacesToExport', [])) <= set(variables.get('NamespacesToExport', [])), \
        'Incomplete inherited product config: preserve CUSTOM_BUILD=sheng for QCOM setup'
    assert (str(owned / 'Android.bp') + '\n') in inputs[2].read_text()
    with (retained / '.sheng-device-modules.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        active = subprocess.check_output(['ps', '-eo', 'comm='], text=True).splitlines()
        assert not any(name.strip() in ('soong_build', 'ninja') for name in active), 'Another build is active'
        work.mkdir()
        (work / '.out-dir').touch()
        report.mkdir(parents=True)
        soong = work / 'soong'
        soong.mkdir()
        (soong / '.temp').mkdir()
        relocated, relocation_count = relocate_testcase_outputs(
            variables, product_config.relative_to(rom), relative_work)
        (soong / 'soong.custom_sheng.variables').write_text(json.dumps(relocated, indent=2))
        if args.source_variants:
            blueprints = discover_blueprints(rom)
            missing = set(inputs[2].read_text().splitlines()) - set(blueprints)
            assert not missing, 'Fresh finder omitted retained source definitions: ' + repr(sorted(missing)[:20])
            (work / 'Android.bp.list').write_text('\n'.join(blueprints) + '\n')
        else:
            shutil.copy2(inputs[2], work / 'Android.bp.list')
        date_copy = work / date_relative
        date_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(date_source, date_copy)
        assert sha(date_copy) == before[str(date_source)]
        available.update(OUT_DIR=str(relative_work), OUT=str(work / 'target/product/sheng'),
                         ANDROID_SOONG_HOST_OUT=str(work / 'host/linux-x86'),
                         LOG_DIR=str(work), TMPDIR=str(soong / '.temp'),
                         TOP=str(rom), PWD=str(rom),
                         BUILD_DATETIME_FILE=str(relative_work / date_relative))
        available_path = soong / 'environment.available'
        available_path.write_text(json.dumps([dict(Key=k, Value=v) for k, v in available.items()]))
        command = [str(builder), '--top', str(rom), '--out', str(relative_work),
                   '--soong_out', str(relative_work / 'soong'),
                   '--soong_variables', str(relative_work / 'soong/soong.custom_sheng.variables'),
                   '-o', str(relative_work / 'soong/build.custom_sheng.ninja'),
                   '--kati_suffix=-custom_sheng', '--kati_enabled',
                   '--partial-analysis-targets=' + ','.join(targets),
                   '-l', str(relative_work / 'Android.bp.list'),
                   '--available_env', str(relative_work / 'soong/environment.available'),
                   '--used_env', str(relative_work / 'soong/environment.used'), 'Android.bp']
        receipt = dict(passed=False, scope='official target-closure graph, retained product config',
                       command=command, input_sha256=before, storage=storage,
                       work=str(work), partial_analysis=True, full_product_graph_verified=False,
                       product_config=str(product_config),
                       source_variants=args.source_variants, targets=targets,
                       module_list_sha256=sha(work / 'Android.bp.list'),
                       module_list_rescanned=args.source_variants,
                       retained_build_datetime_sha256=sha(date_copy),
                       build_datetime_source=str(date_source),
                       relocated_compatibility_testcase_paths=relocation_count,
                       product_make_install_verified=False, compiled=False,
                       device_access=False, flashed=False)
        receipt['host_stop_floor_bytes'] = HOST_FLOOR_BYTES
        receipt['graph_growth_reserve_bytes'] = GRAPH_GROWTH_RESERVE_BYTES
        receipt_path = report / 'analysis.json'
        receipt_path.write_text(json.dumps(receipt, indent=2))
        # Blueprint explicitly resets GOMAXPROCS to runtime.NumCPU(), ignoring
        # the initial environment limit. Affinity bounds NumCPU without changing
        # any source or product-analysis setting.
        cpu_affinity = set(sorted(os.sched_getaffinity(0))[:4])
        receipt['cpu_affinity'] = sorted(cpu_affinity)
        receipt_path.write_text(json.dumps(receipt, indent=2))
        environment = dict(os.environ, GOMEMLIMIT='4GiB', GOGC='15', GOMAXPROCS='4',
                           TMPDIR=str(soong / '.temp'))
        with (report / 'soong.stdout').open('wb') as stdout, (report / 'soong.stderr').open('wb') as stderr:
            process = subprocess.Popen(command, cwd=rom, env=environment,
                                       stdout=stdout, stderr=stderr, start_new_session=True,
                                       preexec_fn=lambda: os.sched_setaffinity(0, cpu_affinity))
            print(json.dumps(dict(started_pid=process.pid, work=str(work))), flush=True)
            lowest_free = shutil.disk_usage('/mnt/c').free
            stopped = None
            while process.poll() is None:
                lowest_free = min(lowest_free, shutil.disk_usage('/mnt/c').free)
                if lowest_free < HOST_FLOOR_BYTES:
                    stopped = 'C volume fell below 6 GiB guard'
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    break
                time.sleep(2)
            process.wait()
        unchanged = all(sha(Path(path)) == digest for path, digest in before.items())
        receipt.update(returncode=process.returncode, guard_stop=stopped,
                       minimum_host_free_bytes=lowest_free, inputs_unchanged=unchanged,
                       graph_generation_passed=(process.returncode == 0 and unchanged and stopped is None),
                       passed=(process.returncode == 0 and unchanged and stopped is None))
        receipt_path.write_text(json.dumps(receipt, indent=2))
        print(json.dumps({k: v for k, v in receipt.items() if k != 'input_sha256'}, indent=2), flush=True)
        assert process.returncode == 0 and unchanged and stopped is None, 'Analysis failed; preserve logs'


if __name__ == '__main__':
    main()
