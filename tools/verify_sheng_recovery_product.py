#!/usr/bin/env python3
"""Check normal Recovery build outputs without packaging or flashing an image."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


SOURCE = Path(__file__).resolve().parents[1]
FIRMWARE_TYPE = 'vendor_sysfs_sheng_firmware_path'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_touch(recovery, clang, host, run, status):
    assert {'sheng-recovery-touch-runtime', 'libsheng_recovery_touchsensor',
            'libsheng_recovery_tensorflowlite_touch'} <= set(status['modules'])
    inputs = json.loads((SOURCE / 'rootdir/recovery/touch-inputs.json').read_text())
    for entry in inputs['entries']:
        assert sha(recovery / entry['installed']) == entry['sha256'], entry['installed']
    script = recovery / 'system/bin/sheng-recovery-touch'
    rc = recovery / 'system/etc/init/init.recovery.sheng-touch.rc'
    assert script.read_bytes() == (SOURCE / 'rootdir/recovery/touch.sh').read_bytes()
    assert rc.read_bytes() == (SOURCE / 'rootdir/recovery/init.recovery.sheng-touch.rc').read_bytes()
    run([host / 'host_init_verifier', rc], 'touch-init-verification.txt')
    # Android's recovery root exposes ODM firmware through this root-relative
    # alias. Check the target without following it into the host filesystem.
    assert (recovery / 'odm/firmware').is_symlink()
    assert (recovery / 'odm/firmware').readlink() == Path('/vendor/odm/firmware')
    services = []
    for candidate in [*recovery.glob('init.recovery*.rc'),
                      *recovery.glob('system/etc/init/*.rc')]:
        for line in candidate.read_text().splitlines():
            if line.startswith('service sheng-recovery-touch '):
                services.append(str(candidate.relative_to(recovery)))
    assert services == ['system/etc/init/init.recovery.sheng-touch.rc'], services

    runtime = recovery / 'system/bin/touch_report_debug'
    assert runtime.stat().st_mode & 0o111, 'Touch processor is not executable'
    # Resolve the complete DT_NEEDED closure in the actual Recovery output,
    # including loader-provided libdl symbols and ELF symbol versions.
    pending = [runtime]
    closure = {}
    exports = set()
    imports = {}
    while pending:
        path = pending.pop()
        relative = str(path.relative_to(recovery))
        if relative in closure:
            continue
        assert path.is_file() and not path.is_symlink(), relative
        elf = run([clang / 'llvm-readelf', '-h', '-l', '-d', '--dyn-syms', path],
                  'touch-elf-' + path.name + '.txt')
        assert re.search(r'Machine:\s+AArch64', elf), relative
        needed = re.findall(r'\(NEEDED\).*?\[([^]]+)\]', elf)
        pending.extend(recovery / 'system/lib64' / name for name in needed)
        for interpreter in re.findall(r'Requesting program interpreter: ([^]]+)\]', elf):
            assert interpreter == '/system/bin/linker64'
            pending.append(recovery / interpreter.lstrip('/'))
        required = set()
        for line in elf.splitlines():
            fields = line.split()
            if len(fields) < 8 or not fields[0].endswith(':'):
                continue
            if fields[4] not in ('GLOBAL', 'WEAK'):
                continue
            symbol = fields[7]
            if fields[6] == 'UND':
                if fields[4] == 'GLOBAL':
                    required.add(symbol)
            elif fields[5] in ('DEFAULT', 'PROTECTED'):
                exports.add(symbol.replace('@@', '@'))
                if '@@' in symbol or '@' not in symbol:
                    exports.add(symbol.split('@', 1)[0])
        imports[relative] = required
        closure[relative] = {'sha256': sha(path), 'needed': needed}
    unresolved = {name: sorted(symbols - exports) for name, symbols in imports.items()
                  if symbols - exports}
    assert not unresolved, unresolved
    return dict(passed=True, accepted_r59_input_count=len(inputs['entries']),
                accepted_r59_inputs=inputs['entries'], script_sha256=sha(script),
                init_rc_sha256=sha(rc), single_service_definition_verified=True,
                elf_closure=closure, strong_imports_checked=sum(map(len, imports.values())),
                unresolved_strong_imports=unresolved, hardware_tested=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--build-work', type=Path, required=True)
    parser.add_argument('--accepted-policy', type=Path, required=True)
    parser.add_argument('--accepted-policy-receipt', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--include-touch', action='store_true')
    args = parser.parse_args()
    rom = args.rom.resolve(strict=True)
    build = args.build_work.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    commands = []

    def run(command, log):
        result = subprocess.run(list(map(str, command)), cwd=rom,
                                text=True, capture_output=True)
        commands.append({'argv': list(map(str, command)), 'returncode': result.returncode,
                         'log': log})
        (output / log).write_text(result.stdout + result.stderr)
        (output / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        if result.returncode:
            raise RuntimeError(f'{log}: command exited {result.returncode}')
        return result.stdout

    status = json.loads((build / 'status.json').read_text())
    assert status['normal_module_build_passed'] and status['postbuild_checks_completed']
    assert {'librecovery_ui_ext', 'sepolicy.recovery', 'vendor_sepolicy.cil',
            'init.recovery.qcom.rc'} <= set(status['modules'])
    assert json.loads((build / 'source-mirror.json').read_text())['passed']
    for name in ('status.json', 'source-sync.json', 'source-mirror.json',
                 'prebuild-upstream-audit.json', 'prebuild-recovery-upstream-audit.json',
                 'postbuild-upstream-audit.json'):
        shutil.copy2(build / name, output / name)

    product = rom / 'out/target/product/sheng'
    recovery = product / 'recovery/root'
    installed = {}
    for relative, target in (
        ('rootdir/etc/init.recovery.qcom.rc', 'system/etc/init/init.recovery.qcom.rc'),
        ('rootdir/recovery/hardware.sh', 'system/bin/sheng-recovery-hardware'),
        ('rootdir/recovery/late-modules.sh', 'system/bin/sheng-recovery-late-modules'),
        ('rootdir/recovery/init.recovery.sheng-late-modules.rc',
         'system/etc/init/init.recovery.sheng-late-modules.rc'),
    ):
        assert (SOURCE / relative).read_bytes() == (recovery / target).read_bytes(), relative
        installed[target] = sha(recovery / target)
    host = rom / 'out/host/linux-x86/bin'
    run([host / 'host_init_verifier', recovery / 'system/etc/init/init.recovery.qcom.rc'],
        'init-verification.txt')

    clang = rom / 'prebuilts/clang/host/linux-x86/clang-r596125/bin'
    checker = output / 'check-firmware-policy'
    run([clang / 'clang', '-Wall', '-Wextra', '-Werror',
         '-I', rom / 'external/selinux/libsepol/include',
         SOURCE / 'tools/check_sheng_recovery_policy.c',
         rom / 'out/soong/.intermediates/external/selinux/libsepol/libsepol/linux_glibc_x86_64_static/libsepol.a',
         '-o', checker], 'policy-checker-build.txt')
    policy = recovery / 'sepolicy'
    run([checker, policy], 'compiled-policy-checks.txt')
    accepted = json.loads(args.accepted_policy_receipt.read_text())
    assert sha(args.accepted_policy) == accepted['candidate_policy_sha256']
    before = run([host / 'sepolicy-analyze', args.accepted_policy, 'permissive'],
                 'accepted-permissive.txt').splitlines()
    after = run([host / 'sepolicy-analyze', policy, 'permissive'],
                'normal-build-permissive.txt').splitlines()
    assert set(before) == set(after), 'Recovery permissive domain set changed'
    vendor_cil = product / 'vendor/etc/selinux/vendor_sepolicy.cil'
    assert FIRMWARE_TYPE not in vendor_cil.read_text(), 'Recovery-only type leaked into Android policy'

    library = recovery / 'system/lib64/librecovery_ui_ext.so'
    elf = run([clang / 'llvm-readelf', '-h', '-d', '--dyn-syms', library], 'ui-elf.txt')
    assert re.search(r'Machine:\s+AArch64', elf)
    assert any('make_device' in line and 'GLOBAL' in line and 'UND' not in line
               for line in elf.splitlines()), 'Recovery extension factory is not exported'
    assert b'ShengRecoveryUI battery events' in library.read_bytes()
    needed = re.findall(r'\(NEEDED\).*?\[([^]]+)\]', elf)
    assert 'librecovery_ui.so' in needed
    dependencies = {name: sha(library.parent / name) for name in needed}
    link_commands = run([rom / 'prebuilts/build-tools/linux-x86/bin/ninja',
                         '-f', 'out/combined-lineage_sheng.ninja', '-t', 'commands',
                         library.relative_to(rom)], 'ui-build-commands.txt')
    assert 'ShengRecoveryUI.cpp' in link_commands and 'librecovery_ui_sheng.a' in link_commands
    assert '--no-undefined' in link_commands

    report = {
        'date_utc': datetime.now(timezone.utc).isoformat(), 'passed': True,
        'normal_module_build_passed': True, 'build_work': str(build),
        'full_product_build_passed': False, 'image_packaged': False,
        'flashed': False, 'hardware_tested': False,
        'installed_scripts': installed,
        'recovery_policy_sha256': sha(policy),
        'accepted_policy_sha256': sha(args.accepted_policy),
        'compiled_firmware_label_and_access_checks_passed': True,
        'permissive_domains_unchanged': True, 'existing_permissive_domains': after,
        'firmware_type_absent_from_android_policy': True,
        'vendor_policy_sha256': sha(vendor_cil),
        'ui_library_sha256': sha(library), 'ui_direct_dependencies': dependencies,
        'ui_factory_and_device_library_link_verified': True,
        'scope_note': 'Normal firmware/UI/policy build outputs; standalone image assembly and hardware acceptance remain separate.',
    }
    if args.include_touch:
        report['touch'] = verify_touch(recovery, clang, host, run, status)
        report['scope_note'] = 'Normal firmware/UI/policy/touch build outputs; complete image assembly and hardware acceptance remain separate.'
    (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
