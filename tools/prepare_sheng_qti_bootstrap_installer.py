#!/usr/bin/env python3
"""Prepare the sole QTI installer from a normal-built and isolated-tested pair."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import stat

from build_sheng_qti_bootstrap_candidate import BOOTSTRAP_LIBS, PROFILES, sha
from postprocess_vendor import install_qti_audio_bootstrap, install_qti_bootstrap
from record_sheng_qti_bootstrap_build import SOURCES, completed_normal_build


def acquire_output_lock(rom, inherited_fd=None):
    """Share the wrapper's open lock description, or acquire a standalone lock."""
    path = rom / 'out/.sheng-device-modules.lock'
    if inherited_fd is None:
        lock = path.open('a')
    else:
        if inherited_fd < 3:
            raise ValueError('The inherited build lock must be an explicit file descriptor')
        descriptor = os.dup(inherited_fd)
        try:
            actual, expected = os.fstat(descriptor), path.stat()
            if (not stat.S_ISREG(actual.st_mode)
                    or (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino)):
                raise ValueError('The inherited descriptor is not this ROM output lock')
            lock = os.fdopen(descriptor, 'a')
        except BaseException:
            os.close(descriptor)
            raise
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        lock.close()
        raise ValueError('Another build owns the output; candidate selection was not changed') from None
    # Closing a duplicate must not explicitly unlock the wrapper's descriptor.
    return lock


def qualify(build, runtime, rom, source):
    evidence = json.loads((build / 'build.json').read_text())
    tested = json.loads((runtime / 'runtime.json').read_text())
    if evidence.get('normal_module_build_passed') is not True or not evidence['compiled']:
        raise ValueError('Direct compiler experiments cannot qualify the product installer')
    run = Path(evidence['normal_build'])
    profile = evidence.get('profile', 'video')
    completed_normal_build(run, profile)
    if sha(run / 'status.json') != evidence['normal_build_status_sha256']:
        raise ValueError('The normal-build receipt changed')
    if tested.get('normal_module_build_passed') is not True or tested['passed'] is not True:
        raise ValueError('The exact normal-built pair must pass the isolated runtime probe')
    if tested.get('build_receipt_sha256') != sha(build / 'build.json'):
        raise ValueError('Runtime receipt belongs to another build')
    if not (evidence['seccomp_enabled'] and tested['seccomp_enabled']
            and tested['exit_code'] == 0 and tested['wrapper_enumeration_natural_exit_passed']
            and tested.get('actual_component_create_release_passed',
                           tested.get('actual_video_component_create_release_passed')) is True
            and tested['services_and_baseline_state_unchanged']):
        raise ValueError('Sandbox, wrapper/interface teardown or baseline checks failed')
    if any(tested[key] for key in ('hal_registered', 'flashed', 'system_service_restarted')):
        raise ValueError('Expected an isolated probe without service replacement')
    for state in ('before', 'after'):
        if tested[state]['slot'] != '_a' or tested[state]['selinux'] != 'Enforcing':
            raise ValueError('Runtime baseline does not match the authorized device state')
    if tested['serial'] != 'ca10ede3':
        raise ValueError('Runtime receipt belongs to another device')
    for name in SOURCES:
        digest = evidence['source_hashes'][name]
        if digest != sha(source / name) or digest != sha(rom / 'device/xiaomi/sheng/interfaces/compat/codec2' / name):
            raise ValueError('Candidate source changed after qualification: ' + name)
    for kind, output in evidence['outputs'].items():
        if not (sha(Path(output['path'])) == sha(Path(output['normal_output'])) == output['sha256']
                == tested['output_hashes'][kind]):
            raise ValueError('Qualified output changed: ' + kind)
    if not set(evidence['outputs']['bootstrap']['needed']) <= BOOTSTRAP_LIBS:
        raise ValueError('Bootstrap must not link C2 providers at startup')
    product = rom / 'out/target/product/sheng/vendor'
    for name, digest in tested['input_hashes'].items():
        if sha(product / 'lib64' / name) != digest:
            raise ValueError('Qualified library changed: ' + name)
    for name, digest in tested['policy_hashes'].items():
        if sha(product / 'etc/seccomp_policy' / name) != digest:
            raise ValueError('Qualified sandbox policy changed: ' + name)
    return evidence


def installer(text, evidence, source):
    # The payload now has its own source installer and required plugin list.
    # Reusing a generated prebuilt alias would install the same SONAME twice.
    if evidence.get('profile', 'video') == 'audio':
        return install_qti_audio_bootstrap(text)
    return install_qti_bootstrap(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='Select the qualified candidate in the generated vendor BP')
    args = parser.parse_args()
    rom = args.rom.resolve(strict=True)
    build_lock = None
    if args.apply:
        build_lock = acquire_output_lock(rom)
    source = Path(__file__).resolve().parents[1] / 'interfaces/compat/codec2'
    evidence = qualify(args.build.resolve(strict=True), args.runtime.resolve(strict=True), rom, source)
    vendor = rom / 'vendor/xiaomi/sheng'
    bp = vendor / 'Android.bp'
    before = bp.read_text()
    proposed = installer(before, evidence, source)
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    (work / 'before-Android.bp').write_text(before)
    (work / 'candidate-Android.bp').write_text(proposed)
    service = PROFILES[evidence.get('profile', 'video')]['service']
    unchanged = {str(path.relative_to(vendor)): sha(path) for path in (
        vendor / 'proprietary/vendor/bin/hw' / service,
        vendor / 'proprietary/vendor/etc/init' / (service + '.rc'))}
    if args.apply:
        bp.write_text(proposed)
    if any(sha(vendor / name) != digest for name, digest in unchanged.items()):
        raise ValueError('OEM service or init RC changed')
    receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), applied=args.apply,
                   build_receipt_sha256=sha(args.build / 'build.json'),
                   runtime_receipt_sha256=sha(args.runtime / 'runtime.json'),
                   candidate_sha256=sha(work / 'candidate-Android.bp'), oem_inputs=unchanged,
                   hal_registered=False, flashed=False, system_service_restarted=False,
                   video_boot_failure_fixed=False, product_build_passed=False)
    (work / 'integration.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(work / 'candidate-Android.bp')


if __name__ == '__main__':
    main()
