#!/usr/bin/env python3
"""Reproduce unchanged policy inputs and assemble VINTF for targeted stylus outputs."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import xml.etree.ElementTree as ET

sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[4]
    rom = Path('/root/sheng-lineage/lineage-24.0')
    device = workspace/'device/xiaomi/sheng'
    original = rom/'out/target/product/sheng'
    host = rom/'out/host/linux-x86/bin'
    build = json.loads(args.build.read_text())
    assert build['passed'] and build['targeted_modules_linked'] and not build['normal_module_build_passed']
    work = args.build.resolve().parent
    product = Path(build['product_root'])
    proof_path = work/'policy-vintf-receipt.json'
    assert not proof_path.exists()
    receipt = dict(started_utc=datetime.now(timezone.utc).isoformat(), passed=False,
        normal_module_build_passed=False, targeted_build_receipt_sha256=sha(args.build),
        installed=False, hardware_tested=False, commands=[], inputs_sha256={})
    env = dict(os.environ, LANG='C.UTF-8', LC_ALL='C.UTF-8', LD_LIBRARY_PATH=str(host.parent/'lib64'),
               RELEASE_AIDL_USE_UNFROZEN='false')

    def run(argv, label, stdout=None):
        argv = list(map(str, argv))
        result = subprocess.run(argv, cwd=rom, env=env, capture_output=True, timeout=180)
        (work/(label+'.log')).write_bytes(result.stderr if stdout else result.stdout+result.stderr)
        receipt['commands'].append(dict(argv=argv, exit_code=result.returncode, output=label+'.log'))
        if result.returncode:
            raise RuntimeError(label+': '+result.stderr.decode(errors='replace')[-1200:])
        if stdout: stdout.write_bytes(result.stdout)
        return result.stdout

    def copy(relative):
        destination = product/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original/relative, destination)
        receipt['inputs_sha256'][str(original/relative)] = sha(original/relative)
        return destination

    try:
        rules = json.loads((work/'retained-policy-rules.json').read_text())
        reproduced = {}
        for part in ('plat', 'system_ext', 'product', 'vendor'):
            command = rules['rule m.'+part+'_sepolicy.conf_android_common.conf']
            if command.endswith('.sh'): command = (rom/command).read_text()
            tokens = shlex.split(command[command.index('prebuilts/build-tools/linux-x86/bin/m4 '):])
            redirect = tokens.index('>')
            argv = tokens[:redirect]
            old = rom/tokens[redirect+1]
            assert argv[0].endswith('/m4') and '--fatal-warnings' in argv
            for value in argv:
                if value.endswith('/newline'):
                    newline = rom/value
                    assert newline.is_relative_to(rom/'out/soong/.intermediates/system/sepolicy')
                    if not newline.exists(): newline.write_bytes(b'\n')
                    assert newline.read_bytes() == b'\n'
                if (rom/value).is_file(): receipt['inputs_sha256'][str(rom/value)] = sha(rom/value)
            for path in (rom/'device/xiaomi/sheng/interfaces/input/stylus/sepolicy').rglob('*.te'):
                if part in ('system_ext', 'vendor'):
                    required = ('/vendor/' in str(path) or '/system_ext/public/' in str(path)) if part == 'vendor' else '/system_ext/' in str(path)
                    if required: assert str(path.relative_to(rom)) in argv, path
            output = work/(part+'-source-reproduced.conf')
            run(argv, 'policy-source-'+part, output)
            assert output.read_bytes() == old.read_bytes(), 'Policy configuration changed: '+part
            reproduced[part] = sha(output)
        for part in ('system', 'system_ext', 'product', 'vendor', 'odm'):
            for path in (original/part/'etc/selinux').rglob('*'):
                if path.is_file(): copy(path.relative_to(original))
        # Recompile the complete retained CIL set with neverallow enforcement.
        command = shlex.split(rules['rule m.precompiled_sepolicy_android_common.secilc'].split(' && ', 1)[0])
        command = [value for value in command if value != '-N']
        assert Path(command[0]).name == 'secilc'
        for value in command:
            if value.endswith('.cil'): receipt['inputs_sha256'][str(rom/value)] = sha(rom/value)
        candidate = work/'reproduced-precompiled-sepolicy'
        command[command.index('-o')+1] = str(candidate)
        run(command, 'policy-neverallows')
        precompiled = [product/part/'etc/selinux/precompiled_sepolicy' for part in ('odm', 'vendor')
                       if (product/part/'etc/selinux/precompiled_sepolicy').is_file()]
        assert len(precompiled) == 1 and sha(candidate) == sha(precompiled[0])
        baseline_sync = workspace/'reports/device/20261114-stylus-service/normal-module-build-h96m9f3g/stylus-source-sync.json'
        prior = json.loads(baseline_sync.read_text())['files']
        for relative, digest in build['source_sha256'].items():
            if '/sepolicy/' in relative: assert prior[relative]['sha256'] == digest
        fragment = product/'vendor/etc/vintf/manifest/vendor.lineage.sheng.stylus-service.xml'
        fragment.parent.mkdir(parents=True, exist_ok=True)
        # The retained host assembler embeds pre-freeze AIDL metadata and
        # removes this V1 HAL. Its current source is already a complete frozen
        # fragment, so install that exact declaration and verify the real
        # partition combination later; never change a runtime release flag.
        fragment_source = device/'interfaces/input/stylus/native'/fragment.name
        root = ET.parse(fragment_source).getroot()
        assert root.tag == 'manifest' and root.get('type') == 'device'
        assert root.findtext('hal/name') == 'vendor.lineage.sheng.stylus'
        assert root.findtext('hal/version') == '1' and root.findtext('hal/fqname') == 'IPenController/default'
        assert build['frozen_api_hash'].encode() in (product/'vendor/lib64/vendor.lineage.sheng.stylus-V1-ndk.so').read_bytes()
        shutil.copyfile(fragment_source, fragment)
        matrices = ['hardware/qcom-caf/common/vendor_framework_compatibility_matrix.xml',
            'hardware/xiaomi/vintf/xiaomi_framework_compatibility_matrix.xml',
            'device/xiaomi/sheng/configs/vintf/framework_dolby_matrix.xml',
            'device/xiaomi/sheng/configs/vintf/framework_face_matrix.xml',
            'device/xiaomi/sheng/configs/vintf/framework_stylus_matrix.xml']
        matrix = product/'system/etc/vintf/compatibility_matrix.device.xml'
        matrix.parent.mkdir(parents=True, exist_ok=True)
        for path in matrices: receipt['inputs_sha256'][str(rom/path)] = sha(rom/path)
        # Keep every baseline framework requirement and merge only the
        # device-owned frozen interface. No other HAL version is adjusted.
        baseline_matrix = original/'system/etc/vintf/compatibility_matrix.device.xml'
        matrix_tree = ET.parse(baseline_matrix)
        matrix_root = matrix_tree.getroot()
        assert matrix_root.tag == 'compatibility-matrix' and matrix_root.get('type') == 'framework'
        for hal in list(matrix_root.findall('hal')):
            if hal.findtext('name') == 'vendor.lineage.sheng.stylus': matrix_root.remove(hal)
        current = ET.parse(device/'configs/vintf/framework_stylus_matrix.xml').getroot()
        assert len(current) == 1 and current[0].findtext('version') == '1'
        matrix_root.append(current[0])
        ET.indent(matrix_tree, space='    ')
        matrix_tree.write(matrix, encoding='utf-8', xml_declaration=True)
        receipt['inputs_sha256'][str(baseline_matrix)] = sha(baseline_matrix)
        assert ET.parse(fragment).findtext('hal/version') == '1'
        assert any(hal.findtext('name') == 'vendor.lineage.sheng.stylus' for hal in ET.parse(matrix).findall('hal'))
        dependencies = set()
        for relative in ('vendor/bin/hw/vendor.lineage.sheng.stylus-service', 'vendor/lib64/vendor.lineage.sheng.stylus-V1-ndk.so'):
            import re
            text = run(['/usr/bin/readelf', '-d', product/relative], 'dependencies-'+Path(relative).name).decode()
            dependencies.update(re.findall(r'\(NEEDED\).*?\[(.*?)\]', text))
        for name in dependencies:
            if name == 'vendor.lineage.sheng.stylus-V1-ndk.so': continue
            for part in ('vendor', 'system'):
                relative = Path(part)/'lib64'/name
                if (original/relative).is_file(): copy(relative); break
            else:
                expected = '/apex/com.android.runtime/lib64/bionic/'+name
                link = original/'system/lib64'/name
                if name not in ('libc.so', 'libdl.so', 'libm.so') or not link.is_symlink() or os.readlink(link) != expected:
                    raise ValueError('Missing linked library: '+name)
                receipt.setdefault('retained_runtime_apex_libraries', {})[name] = expected
        copy(Path('vendor/bin/hw/vendor.qti.media.c2@1.0-service'))
        snapshot = Path(build['snapshot_guard']).parent/'stylus-source-sync.json'
        shutil.copyfile(snapshot, work/'stylus-source-sync.json')
        assert sha(work/'stylus-source-sync.json') == build['source_sync_sha256']
        assert all(sha(Path(path)) == digest for path, digest in receipt['inputs_sha256'].items())
        receipt.update(passed=True, unchanged_policy_configurations_reproduced=reproduced,
            complete_policy_recompiled=True, neverallows_enabled=True,
            precompiled_policy_reproduced_sha256=sha(candidate), frozen_vintf_assembled=True,
            vintf_from_explicit_frozen_source=True, other_baseline_matrix_requirements_preserved=True,
            outputs_sha256={str(path.relative_to(product)): sha(path) for path in product.rglob('*') if path.is_file()})
        print('Current policy configurations reproduced, full policy recompiled with neverallows, frozen VINTF assembled.', flush=True)
    except BaseException as error:
        receipt['error'] = repr(error)
        raise
    finally:
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        proof_path.write_text(json.dumps(receipt, indent=2)+'\n')


if __name__ == '__main__': main()
