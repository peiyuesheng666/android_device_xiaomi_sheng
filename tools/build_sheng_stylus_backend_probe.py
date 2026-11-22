#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compile only the stylus sources from retained arguments, without loading a Ninja graph."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    workspace = Path(__file__).resolve().parents[4]
    source = workspace/'device/xiaomi/sheng/interfaces/input/stylus'
    charge_source = workspace/'device/xiaomi/sheng/interfaces/input/pen/common'
    rom = Path('/root/sheng-lineage/lineage-24.0')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path)
    parser.add_argument('--toolchain-receipt', type=Path, default=Path(
        '/root/sheng-lineage/hardware-diagnostics/qti-bootstrap-20261113-r4/build.json'))
    parser.add_argument('--run-tests', action='store_true',
                        help='Also run native/protocol tests when their covered sources have changed')
    args = parser.parse_args()
    if args.work:
        work = args.work.resolve()
        work.mkdir(parents=True, exist_ok=False)
    else:
        reports = workspace/'reports/device/20261114-stylus-service'
        reports.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix='backend-compilation-', dir=reports))
    environment = dict(os.environ, LANG='C.UTF-8', LC_ALL='C.UTF-8',
                       LD_LIBRARY_PATH=str(rom/'out/host/linux-x86/lib64'))
    receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), passed=False,
                   kind='isolated-frozen-stylus-backend-compilation',
                   normal_soong_module_build=False, full_product_build_passed=False,
                   installed=False, runtime_tested=False, ninja_graph_loaded=False,
                   compiler_wrapper_changed=False, public_source_changed=False,
                   source_api_snapshot_written=False, commands=[])

    def snapshot():
        return {str(path.relative_to(source)): sha(path)
                for path in sorted(source.rglob('*')) if path.is_file()}

    def charge_snapshot():
        return {str(path.relative_to(workspace/'device/xiaomi/sheng')): sha(path)
                for path in sorted(charge_source.rglob('*.java'))}

    def run(argv, label):
        command = list(map(str, argv))
        result = subprocess.run(command, cwd=rom, env=environment,
                                text=True, capture_output=True, timeout=180)
        (work/(label+'.log')).write_text(result.stdout+result.stderr)
        receipt['commands'].append(dict(command=command, exit_code=result.returncode,
                                        output=label+'.log'))
        if result.returncode:
            raise RuntimeError(label+' failed: '+result.stderr[-2000:])
        return result.stdout

    try:
        source_before = snapshot()
        charge_before = charge_snapshot()
        receipt['shared_source_sha256'] = charge_before
        retained_path = args.toolchain_receipt.resolve(strict=True)
        retained = json.loads(retained_path.read_text())
        command = list(retained['commands']['bootstrap'][0])
        if (retained.get('compiled') is not True or not command
                or not all(isinstance(arg, str) for arg in command)
                or Path(command[0]).name != 'clang++'
                or command.count('-c') != 1 or command.count('-o') != 1
                or command.count('-MF') != 1
                or not command[-1].endswith('/qti_bootstrap.cpp')
                or any(arg in ('&&', ';', '|') for arg in command)):
            raise ValueError('Expected retained vendor compiler arguments; no graph fallback is allowed')
        compiler = (rom/command[0]).resolve(strict=True)
        clang_root = (rom/'prebuilts/clang/host/linux-x86').resolve(strict=True)
        if not compiler.is_relative_to(clang_root):
            raise ValueError('The retained command must use the pinned Android compiler')
        receipt.update(compiler_commands_source=str(retained_path),
                       compiler_commands_sha256=sha(retained_path), compiler_sha256=sha(compiler),
                       actual_source_sha256=source_before,
                       helper_sha256=sha(Path(__file__)))
        aidl = rom/'out/host/linux-x86/bin/aidl'
        api = source/'aidl_api/vendor.lineage.sheng.stylus/1'
        interface = source/'aidl/vendor/lineage/sheng/stylus/IPenController.aidl'
        frozen_interface = api/'vendor/lineage/sheng/stylus/IPenController.aidl'
        frozen_hash = (api/'.hash').read_text().strip()
        if (not re.fullmatch(r'[0-9a-f]{40}', frozen_hash)
                or not re.search(r'\bfrozen:\s*true\s*,', (source/'Android.bp').read_text())):
            raise ValueError('The frozen V1 interface is required')
        # Use the platform's actual hash generator, with its output confined to
        # this new report directory. Never update the source .hash or current/.
        hash_generator = rom/'system/tools/aidl/build/hash_gen.sh'
        if any(char.isspace() for char in str(api)+str(work)):
            raise ValueError('The platform hash generator requires paths without whitespace')
        run(['bash', hash_generator, api, 'latest-version', work/'api.hash'], 'frozen-api-hash')
        if (work/'api.hash').read_text().strip() != frozen_hash:
            raise ValueError('Frozen API content differs from its recorded V1 hash')
        dumped = work/'source-api'
        run([aidl, '--dumpapi', '--structured', '--stability=vintf',
             '-I'+str(source/'aidl'), '--out='+str(dumped), interface], 'dump-source-api')
        run([aidl, '--structured', '--stability=vintf', '--checkapi=equal',
             api, dumped], 'compare-frozen-api')
        common = [aidl, '--structured', '--stability=vintf', '--version=1',
                  '--hash='+frozen_hash, '--min_sdk_version=35', '-I'+str(api)]
        generated, headers = work/'generated', work/'headers'
        run([*common, '--lang=ndk', '--out='+str(generated),
             '--header_out='+str(headers), frozen_interface], 'generate-ndk')
        run([*common, '--lang=java', '--out='+str(work/'java'),
             frozen_interface], 'generate-java')
        for root in (generated, work/'java'):
            if not any(frozen_hash.encode() in path.read_bytes()
                       for path in root.rglob('*') if path.is_file()):
                raise ValueError('Generated interface does not contain the frozen hash')
        receipt.update(api_frozen=True, frozen_api_version=1, frozen_api_hash=frozen_hash,
                       aidl_compiler_sha256=sha(aidl), hash_generator_sha256=sha(hash_generator),
                       aidl_source_sha256=sha(interface))
        native = sorted((source/'native').glob('*.cpp')) + sorted(generated.rglob('*.cpp'))
        if len({path.stem for path in native}) != len(native):
            raise ValueError('Native object names must be unique')
        objects = []
        for path in native:
            target = work/(path.stem+'.o')
            argv = list(command)
            argv[-1] = str(path)
            argv[argv.index('-o')+1] = str(target)
            # Retained QTI arguments use bootstrap.d, not bootstrap.o.d.
            # Redirect this explicitly so the old evidence is never overwritten.
            argv[argv.index('-MF')+1] = str(target)+'.d'
            argv = ['aarch64-linux-android35' if arg.startswith('aarch64-linux-android')
                    else arg for arg in argv]
            argv += ['-I'+str(headers), '-I'+str(source/'native')]
            argv += ['-Iframeworks/native/libs/binder/ndk/'+name
                     for name in ('include_cpp', 'include_ndk', 'include_platform')]
            run(argv, 'native-'+path.stem)
            objects.append(target)
        receipt.update(native_vendor_objects_compiled=True,
                       objects_sha256={path.name: sha(path) for path in objects})
        jars = [rom/'out/soong/.intermediates/frameworks/base/framework-minus-apex/android_common/combined/framework.jar',
                rom/'out/soong/.intermediates/packages/modules/Bluetooth/framework/framework-bluetooth.impl/android_common/combined/framework-bluetooth.jar',
                rom/'out/soong/.intermediates/libcore/core-libart/android_common_apex31/javac/core-libart.jar']
        java = (sorted((work/'java').rglob('*.java')) + sorted((source/'src').rglob('*.java'))
                + sorted((source/'app').rglob('*.java')) + sorted(charge_source.rglob('*.java')))
        jdk = rom/'prebuilts/jdk/jdk21/linux-x86/bin'
        run([jdk/'javac', '-J-Xmx256m', '-source', '8', '-target', '8', '-Xlint:-options',
             '-encoding', 'UTF-8', '-cp', os.pathsep.join(map(str, jars)),
             '-d', work/'java-classes', *java], 'compile-java')
        receipt.update(aidl_java_compiled=True, app_java_compiled=True,
                       classpath_sha256={str(path): sha(path) for path in jars},
                       classes_sha256={str(path.relative_to(work)): sha(path)
                                       for path in (work/'java-classes').rglob('*.class')})
        if args.run_tests:
            test = work/'pen-controller-test'
            run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                 '-I'+str(source/'native'), source/'native/PenController.cpp',
                 source/'native/PenLeaseJournal.cpp', source/'tests/PenControllerTest.cpp',
                 '-o', test], 'build-native-test')
            stdout = run([test], 'native-test')
            receipt['host_test'] = dict(passed=True, stdout=stdout,
                assertions=int(re.search(r'assertions=(\d+)', stdout)[1]), binary_sha256=sha(test))
            test_classes = work/'protocol-test-classes'
            run([jdk/'javac', '-encoding', 'UTF-8', '-d', test_classes,
                 source/'src/org/lineageos/sheng/stylus/PenModel.java',
                 source/'src/org/lineageos/sheng/stylus/MippProfile.java',
                 source/'tests/PenProtocolOfflineTest.java'], 'build-protocol-test')
            stdout = run([jdk/'java', '-cp', test_classes,
                          'org.lineageos.sheng.stylus.PenProtocolOfflineTest'], 'protocol-test')
            receipt['protocol_test'] = dict(passed=True, stdout=stdout)
        if (snapshot() != source_before or charge_snapshot() != charge_before
                or sha(retained_path) != receipt['compiler_commands_sha256']):
            raise ValueError('Source files or retained compiler evidence changed during compilation')
        receipt.update(source_files_unchanged=True, passed=True)
    except Exception as error:
        receipt['error'] = repr(error)
    finally:
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        (work/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(dict(work=str(work), passed=receipt['passed'],
                         native_objects=len(receipt.get('objects_sha256', {})),
                         frozen_api_hash=receipt.get('frozen_api_hash'),
                         ninja_graph_loaded=False, normal_soong_module_build=False)))
    if not receipt['passed']:
        print(receipt['error'])
        raise SystemExit(1)


if __name__ == '__main__':
    main()
