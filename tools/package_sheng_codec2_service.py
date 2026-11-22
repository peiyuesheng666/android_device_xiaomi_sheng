#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Package qualified native service repairs over the installed vendor image."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import shutil
import sys

from package_sheng_batch_helpers import complete_metadata, merge_parent, publish_batch, sha, stage_erofs
from package_sheng_model_followup import HOST, ROM, run
from build_sheng_qti_bootstrap_candidate import BOOTSTRAP_LIBS, PROFILES
from verify_sheng_qti_service_elf import verify as verify_elf
from prepare_sheng_dolby_policy_update import validate as validate_policy


def qualify(device, build_path, runtime_path):
    build = json.loads(build_path.read_text())
    runtime = json.loads(runtime_path.read_text())
    assert build['compiled'] and build['targeted_module_build_passed']
    assert not build['normal_module_build_passed'] and not build['ninja_graph_loaded']
    assert not build['frame_diagnostic'] and not build.get('pool_diagnostic') and build['seccomp_enabled']
    assert runtime['passed'] and runtime['exit_code'] == 0 and runtime['seccomp_enabled']
    assert runtime['wrapper_enumeration_natural_exit_passed']
    assert runtime['actual_component_create_release_passed']
    assert runtime['component_enumeration_matches_registered_service']
    assert build['profile'] == runtime['profile'] and build['profile'] in PROFILES
    assert runtime['services_and_baseline_state_unchanged']
    assert not any(runtime[key] for key in ('hal_registered', 'flashed', 'system_service_restarted'))
    assert runtime['serial'] == 'ca10ede3'
    assert runtime['build_receipt_sha256'] == sha(build_path)
    if build['profile'] == 'audio' and 'pool_diagnostic' in build:
        pool_probe = runtime['alac_hidl_pool_probe']
        pool_path = Path(pool_probe['receipt'])
        assert sha(pool_path) == pool_probe['sha256']
        pool = json.loads(pool_path.read_text())
        assert pool['passed'] and pool['planned_service_stop_passed']
        assert pool['services_and_boot_unchanged'] and pool['remote_files_removed']
        assert pool['components'] and all(pool['components'].values())
        assert pool['source_hashes'] == build['source_hashes']
        assert pool['production_build_sha256'] == sha(build_path)
    for state in ('before', 'after'):
        assert runtime[state]['slot'] == '_a' and runtime[state]['selinux'] == 'Enforcing'
        assert runtime[state]['kernel'] == '5.15.220-gf9ca2b71f672'
    assert set(build['outputs']) == {'bootstrap', 'payload'}
    assert set(build['outputs']['bootstrap']['needed']) <= BOOTSTRAP_LIBS
    sources = {}
    for name, digest in build['source_hashes'].items():
        relative = 'interfaces/compat/codec2/' + name
        assert sha(device / relative) == digest
        sources[relative] = digest
    for name, digest in build['input_sha256'].items():
        assert sha(Path(name)) == digest, name
    assert sha(device / 'tools/build_sheng_qti_bootstrap_candidate.py') == build['builder_sha256']
    assert sha(Path(build['preaudit'])) == build['preaudit_sha256']
    for kind, output in build['outputs'].items():
        assert sha(Path(output['path'])) == output['sha256'] == runtime['output_hashes'][kind]
    return build, runtime, sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, action='append', default=[])
    parser.add_argument('--runtime', type=Path, action='append', default=[])
    parser.add_argument('--backends', type=Path, help='Prepared original audio decoder backend receipt')
    parser.add_argument('--startup', type=Path, help='Prepared certificate runtime and property cleanup receipt')
    parser.add_argument('--policy', type=Path, help='Qualified vendor property policy receipt')
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--file-contexts', type=Path, required=True)
    parser.add_argument('--contexts-manifest', type=Path, required=True,
                        help='Sealed package that produced the installed vendor image and its file contexts')
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[4]
    device = workspace / 'device/xiaomi/sheng'
    lock = (ROM / 'out/.sheng-device-modules.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert len(args.build) == len(args.runtime)
    assert args.build or args.backends or args.startup or args.policy
    candidates, sources, input_hashes, policy_hashes = {}, {}, {}, {}
    for build_arg, runtime_arg in zip(args.build, args.runtime):
        build_path = build_arg.resolve(strict=True)
        runtime_path = runtime_arg.resolve(strict=True)
        build, runtime, source_hashes = qualify(device, build_path, runtime_path)
        profile = build['profile']
        assert profile not in candidates
        for target, values in ((sources, source_hashes), (input_hashes, runtime['input_hashes']),
                               (policy_hashes, runtime['policy_hashes'])):
            assert all(key not in target or target[key] == value for key, value in values.items())
            target.update(values)
        candidates[profile] = dict(build=build, runtime=runtime, build_path=build_path, runtime_path=runtime_path)
    backends = json.loads(args.backends.read_text()) if args.backends else None
    startup = json.loads(args.startup.read_text()) if args.startup else None
    policy = validate_policy(device, args.policy) if args.policy else None
    if policy:
        sources.update(policy['source_sha256'])
    if startup:
        assert startup['kind'] == 'vendor-startup' and startup['application_apk_unchanged']
    for prepared in (backends, startup):
        if not prepared:
            continue
        assert prepared['passed'] and prepared['unchanged_oem_bytes']
        assert not prepared['normal_module_build_passed'] and not prepared['ninja_graph_loaded']
        assert prepared['checks'] and all(row['exit_code'] == 0 for row in prepared['checks'])
        for name, digest in prepared['source_sha256'].items():
            assert sha(device / name) == digest
            assert name not in sources or sources[name] == digest
            sources[name] = digest
        for name, digest in prepared['dependencies_sha256'].items():
            assert sha(Path(name)) == digest
        for relative, item in prepared['entries'].items():
            assert sha(Path(item['source'])) == sha(Path(item['original'])) == item['sha256']
    for relative in ('tools/postprocess_vendor.py', 'tools/package_sheng_codec2_service.py',
                     'tools/verify_sheng_qti_service_elf.py'):
        sources[relative] = sha(device / relative)
    baseline_path = args.baseline.absolute()
    baseline_reference = baseline_path.relative_to(workspace).as_posix()
    baseline_hash = sha(baseline_path)
    baseline = json.loads(baseline_path.read_text())
    assert baseline['kind'] in ('product-app-layout', 'product-pen-ui', 'codec2-service-update',
                                'vendor-runtime-update', 'ape-extractor-update')
    if startup:
        assert startup['baseline_sha256'] == baseline_hash
        assert sha(Path(startup['baseline_manifest'])) == baseline_hash
    if policy:
        assert policy['baseline_sha256'] == baseline_hash
        assert sha(Path(policy['baseline_manifest'])) == baseline_hash
    assert baseline['complete_avb_chain_verified']
    assert baseline.get('stylus_native_service_unchanged', baseline['native_service_unchanged'])
    rows = baseline['files'] + baseline['unchanged_partition_files']
    assert len(rows) == 14 and len({row['partition'] for row in rows}) == 14
    contexts_record = json.loads(args.contexts_manifest.read_text())
    contexts_hash = contexts_record['scoped_file_contexts_sha256']
    assert sha(args.file_contexts) == contexts_hash
    context_vendor = next(row for row in contexts_record['files'] +
                          contexts_record['unchanged_partition_files'] if row['partition'] == 'vendor')
    assert context_vendor['sha256'] == next(row['sha256'] for row in rows if row['partition'] == 'vendor')
    chain = {row['partition']: Path(baseline['work_dir']) / 'complete-chain' / row['name'] for row in rows}
    for row in rows:
        path = chain[row['partition']]
        assert path.stat().st_size == row['bytes'] and sha(path) == row['sha256'], path
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    assert work.stat().st_dev == Path('/').stat().st_dev
    assert shutil.disk_usage(work).free > 6 * 1024**3
    run(['python3', device / 'tools/prepare_sheng_stylus_swap.py', '--work', work], capture_output=True)
    elf_checks = verify_elf(ROM, [item['build'] for item in candidates.values()], work / 'elf-checks')
    for prepared in (backends, startup):
        if not prepared:
            continue
        checked = json.loads(elf_checks.read_text())
        checked['checks'].extend(prepared['checks'])
        elf_checks.write_text(json.dumps(checked, indent=2) + '\n')
    product = work / 'product'
    # A targeted installed policy may be newer than the normal build output.
    # Use its sealed contexts so unrelated services retain their exact labels.
    contexts = work / 'file-contexts.txt'
    shutil.copyfile(args.file_contexts, contexts)
    entries, nodes = {}, {}
    for profile_name, candidate in candidates.items():
        profile = PROFILES[profile_name]
        for kind, relative in (('bootstrap', 'bin/hw/' + profile['service']),
                               ('payload', 'lib64/' + profile['payload'])):
            output = candidate['build']['outputs'][kind]
            target = product / 'vendor' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(output['path'], target)
            assert sha(target) == output['sha256']
            entries[relative] = dict(source=str(target), bytes=target.stat().st_size, sha256=sha(target))
        nodes['lib64/' + profile['payload']] = dict(
            uid=0, gid=0, mode=0o644, mtime_ns=1230768000 * 10**9, selinux='u:object_r:vendor_file:s0')
    for prepared in (backends, startup):
        if not prepared:
            continue
        for relative, item in prepared['entries'].items():
            assert relative not in entries
            target = product / 'vendor' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item['source'], target)
            assert sha(target) == item['sha256']
            entries[relative] = dict(source=str(target), bytes=target.stat().st_size, sha256=item['sha256'])
            nodes[relative] = dict(uid=0, gid=0, mode=0o644, mtime_ns=1230768000 * 10**9,
                                   selinux='u:object_r:vendor_file:s0')
    if startup:
        item = startup['property_update']
        assert sha(Path(item['source'])) == item['sha256']
        target = product / 'vendor/build.prop'
        shutil.copyfile(item['source'], target)
        entries['build.prop'] = dict(source=str(target), bytes=target.stat().st_size, sha256=sha(target))
    if policy:
        for relative, item in policy['entries'].items():
            assert relative not in entries
            target = product / 'vendor' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item['path'], target)
            entries[relative] = dict(source=str(target), bytes=target.stat().st_size, sha256=sha(target))
    sys.path.insert(0, str(ROM / 'external/avb'))
    import avbtool
    avb = avbtool.Avb()
    baseline_metadata, _ = complete_metadata(chain['vendor'])
    nodes = {relative: metadata for relative, metadata in nodes.items()
             if '/' + relative not in baseline_metadata}
    print('Packaging qualified vendor repairs; checking retained files and inodes.', flush=True)
    vendor, descriptor, stage = stage_erofs('vendor', chain['vendor'], entries, nodes, work, avb, avbtool,
                                           source_product=product, file_contexts=contexts)
    if startup:
        assert stage['baseline_entries']['build.prop'] == (
            'file', startup['property_update']['baseline_sha256'])
    if policy:
        assert stage['baseline_entries']['etc/selinux/vendor_sepolicy.cil'] == (
            'file', policy['vendor_cil_before_sha256'])
        validate_policy(device, args.policy)
    # Compare the actual packaged provider and policy bytes to the isolated probe.
    for name, digest in input_hashes.items():
        assert sha(work / 'vendor-tree/lib64' / name) == digest, name
    for name, digest in policy_hashes.items():
        assert sha(work / 'vendor-tree/etc/seccomp_policy' / name) == digest, name
    outputs = {'vendor': vendor, 'vbmeta': work / 'vbmeta.img'}
    merge_parent(avb, avbtool, chain['vbmeta'], [descriptor], outputs['vbmeta'], 'SHA256_RSA4096', work)
    complete = work / 'complete-chain'
    complete.mkdir()
    for part, path in chain.items():
        (complete / (part + '.img')).symlink_to(outputs.get(part, path).resolve())
    verified = run([HOST / 'avbtool', 'verify_image', '--image', complete / 'vbmeta.img',
                    '--follow_chain_partitions'], capture_output=True, text=True)
    (work / 'avb-verification.log').write_text(verified.stdout + verified.stderr)
    qualified_services = {}
    for profile_name, candidate in candidates.items():
        build_path, runtime_path = candidate['build_path'], candidate['runtime_path']
        qualify(device, build_path, runtime_path)
        qualified_services[profile_name] = dict(
            build_receipt=str(build_path), build_receipt_sha256=sha(build_path),
            isolated_runtime=runtime_path.relative_to(workspace).as_posix(),
            isolated_runtime_sha256=sha(runtime_path))
    assert sha(baseline_path) == baseline_hash
    assert sha(contexts) == contexts_hash
    assert all(sha(device / relative) == digest for relative, digest in sources.items())
    report = dict(
        kind='vendor-runtime-update' if startup or policy else 'codec2-service-update',
        date_utc=datetime.now(timezone.utc).isoformat(),
        baseline_manifest=baseline_reference, baseline_manifest_sha256=baseline_hash,
        baseline_partitions=rows, unchanged_partition_files=[row for row in rows if row['partition'] not in outputs],
        entries={'vendor': entries}, removals={}, partition_reports={'vendor': stage},
        applications=baseline['applications'], product_apps_unchanged=True,
        source_sha256=sources, qualified_services=qualified_services,
        elf_checks=str(elf_checks), elf_checks_sha256=sha(elf_checks),
        qti_input_hashes=input_hashes, qti_policy_hashes=policy_hashes,
        scoped_file_contexts_sha256=contexts_hash,
        scoped_file_contexts=str(contexts), contexts_manifest_sha256=sha(args.contexts_manifest),
        work_dir=str(work), complete_avb_chain_verified=True, partition_sizes_unchanged=True,
        policy_and_vintf_inputs_unchanged=not policy, native_service_unchanged=False,
        stylus_native_service_unchanged=True, systemui_unchanged=True,
        normal_module_build_passed=False, full_product_build_passed=False, ninja_graph_loaded=False,
        targeted_module_build_passed=bool(candidates), targeted_native_validation_passed=True,
        installed=False, e_drive_swap_allowed=False, native_c_staging=True)
    if backends:
        report.update(audio_backends={name: item['sha256'] for name, item in backends['entries'].items()},
                       audio_backends_receipt=str(args.backends.resolve()), audio_backends_receipt_sha256=sha(args.backends))
    if startup:
        report.update(startup_libraries={name: item['sha256'] for name, item in startup['entries'].items()},
                      startup_property_update=startup['property_update'],
                      startup_receipt=str(args.startup.resolve()), startup_receipt_sha256=sha(args.startup))
    if policy:
        report.update(qualified_policy=str(args.policy.resolve()), qualified_policy_sha256=sha(args.policy),
                      boot_policy_neverallows_verified=True, vintf_inputs_unchanged=True,
                      precompiled_cache_ineligible_on_unchanged_partitions=True)
    publish_batch(args.output.resolve(), outputs, report)
    print(args.output / 'build-result.json', flush=True)


if __name__ == '__main__':
    main()
