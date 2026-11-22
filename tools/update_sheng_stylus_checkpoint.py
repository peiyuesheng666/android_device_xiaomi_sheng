#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Record current guarded build state without overwriting retained full-product facts."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

workspace = Path(__file__).resolve().parents[4]
parser = argparse.ArgumentParser()
parser.add_argument('--guard', type=Path, required=True)
parser.add_argument('--session-id', type=int, required=True)
parser.add_argument('--terminal-collected', action='store_true')
parser.add_argument('--artifacts', type=Path)
parser.add_argument('--qti-frame', type=Path)
args = parser.parse_args()
guard_path = args.guard.resolve(strict=True)
guard = json.loads(guard_path.read_text())
checkpoint = workspace/'reports/device/20261113-full-product/continuation-checkpoint.json'
state = json.loads(checkpoint.read_text(encoding='utf-8-sig'))
terminal = 'exit_code' in guard
if args.terminal_collected and not terminal:
    raise RuntimeError('Cannot record a collected terminal session while the build is still active')
report = workspace/'reports/device/20261114-stylus-service'

def latest_verified(pattern, hash_key):
    candidates = []
    for path in report.glob(pattern+'/receipt.json'):
        value = json.loads(path.read_text())
        hashes = value.get(hash_key, {})
        if value.get('passed') is True and hashes and all(
                Path(name).is_file() and hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest
                for name, digest in hashes.items()):
            candidates.append((value['date_utc'], path, value))
    if not candidates: raise RuntimeError('No passing receipt matches current sources: '+pattern)
    _, path, value = max(candidates, key=lambda item: item[0])
    return str(path.relative_to(workspace)), value

actor_path, actor = latest_verified('actor-test-*', 'actual_source_sha256')
input_path, inputs = latest_verified('input-lease-test-*', 'actual_source_sha256')
java_path, java = latest_verified('java-compilation-*', 'source_sha256')
actor_checks = int(re.search(r'actor_checks=(\d+)', actor['stdout'])[1])
input_checks = int(re.search(r'input_lease_checks=(\d+)', inputs['stdout'])[1])
sync = json.loads((guard_path.parent/'stylus-source-sync.json').read_text())
pending_sync = [name for name, value in sync['files'].items()
    if name.startswith('interfaces/input/stylus/') and
    hashlib.sha256((workspace/'device/xiaomi/sheng'/name).read_bytes()).hexdigest() != value['sha256']]
source = workspace/'device/xiaomi/sheng'
api = source/'interfaces/input/stylus'
blueprint = (api/'Android.bp').read_text()
api_hash_path = api/'aidl_api/vendor.lineage.sheng.stylus/1/.hash'
api_hash = api_hash_path.read_text().strip() if api_hash_path.is_file() else None
api_frozen = bool(re.search(r'\bfrozen:\s*true\s*,', blueprint)
                  and api_hash and re.fullmatch(r'[0-9a-f]{40}', api_hash))
package_line = 'PRODUCT_PACKAGES += ShengStylus vendor.lineage.sheng.stylus-service'
packages_enabled = package_line in (source/'device.mk').read_text().splitlines()
if packages_enabled and (not api_frozen or not sync.get('product_packages_enabled')):
    raise RuntimeError('Product inclusion lacks a frozen API or matching source-sync declaration')
artifacts = None
if args.artifacts:
    artifacts = json.loads(args.artifacts.read_text())
    if not (artifacts.get('passed') and artifacts.get('normal_module_build_passed')
            and artifacts.get('api_frozen') and artifacts.get('frozen_api_hash') == api_hash
            and artifacts.get('guard_sha256') == hashlib.sha256(guard_path.read_bytes()).hexdigest()
            and not pending_sync):
        raise RuntimeError('Artifact receipt does not qualify the current guard and frozen sources')
frame = None
if args.qti_frame:
    frame = json.loads(args.qti_frame.read_text())
    checks = frame.get('frame_checks', [])
    if not (frame.get('passed') and frame.get('video_stream_processing_tested')
            and frame.get('serial') == 'ca10ede3' and len(checks) == 8
            and all(item.get('exact') and item.get('differing_bytes') == 0 for item in checks)):
        raise RuntimeError('QTI frame receipt does not prove eight exact decoded frames')
build_work = guard.get('build_work')
if build_work is None:
    lines = (guard_path.parent/'build-output.log').read_text(errors='replace').splitlines()
    paths = [line.partition('Build evidence: ')[2] for line in lines if line.startswith('Build evidence: ')]
    if paths: build_work = paths[-1]
adjustments = [(path, json.loads(path.read_text())) for path in guard_path.parent.glob('memory-resident-adjustment*.json')]
adjustments = [(path, value) for path, value in adjustments if value.get('complete')]
adjustment_path, adjustment = max(adjustments, key=lambda pair: pair[1]['date_utc']) if adjustments else (None, None)
compiler = Path('/root/sheng-lineage/lineage-24.0/out/host/linux-x86/bin/soong_build')
wrapper_active = compiler.read_bytes()[:4] != b'\x7fELF'
history = {item['guard']: item for item in state.get('pen_service_normal_build_previous_runs', [])}
for path in report.glob('normal-module-build-*/guard-status.json'):
    result = json.loads(path.read_text())
    if path == guard_path or 'exit_code' not in result: continue
    key = str(path.relative_to(workspace))
    history.setdefault(key, {}).update(guard=key, module_exit_code=result['exit_code'],
        phase=result.get('phase', 'modules'), normal_module_build_passed=result.get('normal_module_build_passed', False),
        compiler_restored=result.get('compiler_restored'), stopped_reason=result.get('stopped_reason'),
        memory_events=result.get('memory_events'), build_work=result.get('build_work'),
        incremental_analysis_actual=result.get('incremental_analysis_actual'))
phase = guard.get('phase', 'modules')
phase_passed = guard.get('normal_phase_passed', guard['normal_module_build_passed'])
progress = (f'Actor {actor_checks} and input journal {input_checks} checks match current Java sources; '
            f'frozen API V1={api_frozen}, product packages enabled={packages_enabled}; '
            f'normal {phase} phase '+('passed' if phase_passed else 'ended without qualification' if terminal else 'active')+
            '; '+('source resync required' if pending_sync else 'stylus source-sync hashes match')+
            '; '+('APK/ELF/VINTF/policy artifacts verified' if artifacts else 'frozen artifacts still require qualification'))
state.update(date_utc=datetime.now(timezone.utc).isoformat(), goal_complete=False,
    session_id=None if args.terminal_collected else args.session_id,
    ninja_pid=None,
    process_state=(f'Normal {phase} phase ended; '+('artifacts verified' if artifacts else 'review artifact qualification') if terminal else
                   f'Normal {phase} phase active with bounded guest memory and existing swap'),
    latest_progress=progress,
    c_free_bytes=guard.get('latest_sample', guard['initial'])['c_free_bytes'],
    running_wrapper_modified=wrapper_active,
    pen_service_normal_build_guard=str(guard_path.relative_to(workspace)),
    pen_service_normal_build_work=build_work,
    pen_service_build_session_id=args.session_id,
    pen_service_build_session_terminal_collected=args.terminal_collected,
    pen_service_normal_module_build_passed=guard['normal_module_build_passed'] and not pending_sync,
    pen_service_active_build_targets_passed=guard['normal_module_build_passed'],
    pen_service_active_build_matches_current_stylus_sources=not pending_sync,
    pen_service_pending_source_resync=pending_sync,
    pen_service_normal_build_previous_runs=list(history.values()),
    pen_service_normal_build_module_exit_code=guard.get('exit_code'),
    pen_service_normal_build_stopped_reason=guard.get('stopped_reason'),
    pen_service_soong_compiler_restored=guard.get('compiler_restored'),
    pen_service_guard_supervisor_pid=None if terminal else guard.get('supervisor_pid',
        int(Path(adjustment['cgroup']).name.split('-')[-1]) if adjustment else None),
    pen_service_owned_analyzer_pid=None if terminal else guard.get('analyzer_pid'),
    pen_service_source_sync=str((guard_path.parent/'stylus-source-sync.json').relative_to(workspace)),
    build_swap_policy=guard.get('swap_policy', {}).get('policy'),
    e_drive_swap_allowed=guard.get('swap_policy', {}).get('e_drive_swap_allowed'),
    pen_service_swap_receipt=str((guard_path.parent/'swap-priority.json').relative_to(workspace)),
    pen_service_wsl_vm_memory_bytes=guard['initial'].get('guest_vm_memory_bytes'),
    pen_service_actual_incremental_analysis=guard.get('incremental_analysis_actual'),
    pen_service_memory_resident_adjustment=str(adjustment_path.relative_to(workspace)) if adjustment else None,
    pen_service_effective_memory_limits=adjustment['after'] if adjustment and adjustment.get('complete') else
        {key: guard[source] for key, source in [('memory.high', 'memory_high'), ('memory.max', 'memory_max'), ('memory.swap.max', 'swap_max')]},
    pen_service_artifact_verifier_prepared='device/xiaomi/sheng/tools/verify_sheng_stylus_modules.py',
    pen_service_live_driver_review='reports/device/20261114-stylus-service/live-driver-read-review/receipt.json',
    pen_service_init_gentle_kill_wait_ms=200,
    pen_service_actor_test=actor_path,
    pen_service_actor_checks=actor_checks, pen_service_actor_host_test_passed=True,
    pen_service_power_lifecycle_host_test_passed=actor.get('power_lifecycle_suite', False),
    pen_service_power_lifecycle_device_tested=False,
    pen_service_input_lease_test=input_path,
    pen_service_input_lease_checks=input_checks, pen_service_input_lease_host_test_passed=True,
    pen_service_current_java_compilation=java_path,
    pen_service_current_java_compilation_passed=True,
    pen_service_backend_java_receipt_predates_input_journal_v2=True,
    pen_service_input_journal_version=2,
    pen_service_sigterm_cleanup_implemented=True,
    pen_service_sigterm_init_device_tested=False,
    pen_service_product_packages_enabled=packages_enabled, pen_service_api_frozen=api_frozen,
    pen_service_frozen_api_version=1 if api_frozen else None,
    pen_service_frozen_api_hash=api_hash if api_frozen else None,
    pen_service_current_artifacts_verified=artifacts is not None,
    pen_service_artifact_receipt=str(args.artifacts.relative_to(workspace)) if args.artifacts else None,
    pen_service_policy_validated=bool(artifacts and artifacts.get('policy_sha256')),
    current_sources_full_product_validated=False,
    pen_service_native_crash_auto_recovery_passed=False,
    previous_turn_classification=progress)
state.setdefault('pen_permanent_service_installed', False)
state.setdefault('next_steps', [
    'Finish the current stylus source repair batch with isolated checks before combined normal building',
    'Qualify normal-built frozen stylus APK/ELF/VINTF/policy after the source batch is ready',
    'Package and qualify permanent pen service; test dock, wake, Bluetooth reconnect, writing and reboot',
    'Qualify QTI installer and actual service-domain boot/video paths; HDR/DRM remain independent',
    'Complete finalized 6.18 partition integration and full-product hardware regression'])
if frame:
    state.update(latest_qti_frame_runtime=str(args.qti_frame.relative_to(workspace)),
        latest_qti_video_stream_processing_tested=True, latest_qti_exact_decoded_frames=8,
        latest_qti_frame_probe_normal_module_build_passed=frame.get('normal_module_build_passed', False),
        latest_qti_video_boot_failure_fixed=frame.get('video_boot_failure_fixed', False))
checkpoint.write_text(json.dumps(state, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps(dict(checkpoint=str(checkpoint), build_terminal=terminal,
                     retained_full_product_build_passed=state['full_product_build_passed'],
                     goal_complete=False), ensure_ascii=False))
