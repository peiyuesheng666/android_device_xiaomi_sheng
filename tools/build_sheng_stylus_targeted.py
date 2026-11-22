#!/usr/bin/env python3
"""Link current compiled stylus sources without loading or generating a global graph."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import zipfile
from sheng_stylus_evidence import source_hashes_for_guard, controller_assertion_count


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', type=Path, required=True)
    parser.add_argument('--snapshot-guard', type=Path, required=True)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[4]
    device = workspace/'device/xiaomi/sheng'
    source = device/'interfaces/input/stylus'
    rom = Path('/root/sheng-lineage/lineage-24.0')
    host = rom/'out/host/linux-x86/bin'
    work = Path(tempfile.mkdtemp(prefix='targeted-module-build-', dir=workspace/'reports/device/20261114-stylus-service'))
    product = work/'product'
    backend = args.backend.resolve(strict=True)
    prior = json.loads((backend/'receipt.json').read_text())
    receipt = dict(started_utc=datetime.now(timezone.utc).isoformat(), kind='targeted-stylus-link-and-apk',
        passed=False, targeted_modules_linked=False, normal_module_build_passed=False,
        full_product_build_passed=False, ninja_graph_loaded=False, installed=False,
        hardware_tested=False, product_root=str(product), commands=[])
    env = dict(os.environ, LANG='C.UTF-8', LC_ALL='C.UTF-8', LD_LIBRARY_PATH=str(host.parent/'lib64'))

    def save():
        (work/'build-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')

    def run(argv, name):
        argv = list(map(str, argv))
        process_env = dict(env)
        if Path(argv[0]).name in ('java', 'javac'):
            process_env.pop('LD_LIBRARY_PATH', None)
        result = subprocess.run(argv, cwd=rom, env=process_env, capture_output=True, text=True, timeout=180)
        (work/(name+'.log')).write_text(result.stdout+result.stderr)
        receipt['commands'].append(dict(argv=argv, exit_code=result.returncode, output=name+'.log'))
        save()
        if result.returncode:
            raise RuntimeError(name+': '+result.stderr[-1800:])
        return result.stdout+result.stderr

    def target(relative):
        path = product/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    print('Targeted stylus work: '+str(work), flush=True)
    lock = (rom/'out/.sheng-device-modules.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert sha(host/'soong_build') == 'b7187df94fc411e8e0a97989fd8fc694c54f705a8099f7ba1263f2854f7fe43c'
        assert not (host/'soong_build.sheng-real').exists()
        assert prior['passed'] and prior['api_frozen'] and prior['app_java_compiled'] and prior['native_vendor_objects_compiled']
        sources = source_hashes_for_guard(workspace, rom, args.snapshot_guard)
        for relative, expected in prior['actual_source_sha256'].items():
            assert sha(source/relative) == expected, relative
        for relative, expected in prior['objects_sha256'].items():
            assert sha(backend/relative) == expected, relative
        for relative, expected in prior['classes_sha256'].items():
            assert sha(backend/relative) == expected, relative
        for path, expected in prior['classpath_sha256'].items():
            assert sha(Path(path)) == expected, path
        run(['python3', device/'tools/prepare_sheng_stylus_swap.py', '--work', work], 'swap-policy')
        receipt.update(source_sha256=sources, backend_receipt=str(backend/'receipt.json'),
            backend_receipt_sha256=sha(backend/'receipt.json'), snapshot_guard=str(args.snapshot_guard.resolve()),
            snapshot_guard_sha256=sha(args.snapshot_guard), source_sync_sha256=sha(args.snapshot_guard.parent/'stylus-source-sync.json'),
            frozen_api_hash=prior['frozen_api_hash'], frozen_api_version=1,
            builder_sha256=sha(Path(__file__)), compiler_restored=True)
        retained_path = Path('/root/sheng-lineage/hardware-diagnostics/qti-bootstrap-20261113-r4/build.json')
        retained = json.loads(retained_path.read_text())
        common_link = retained['commands']['bootstrap'][1]
        clang = rom/common_link[0]
        assert sha(clang) == prior['compiler_sha256']
        ndk_compile = next(x['command'] for x in prior['commands'] if x['output'] == 'native-IPenController.log')
        ndk_compile = [x for x in ndk_compile if x.lower() not in ('-fpie', '-fpic')]
        ndk_compile += ['-fPIC']
        ndk_compile[ndk_compile.index('-o')+1] = str(work/'IPenController.o')
        ndk_compile[ndk_compile.index('-MF')+1] = str(work/'IPenController.o.d')
        run(ndk_compile, 'compile-frozen-ndk-pic')
        control = work/'libsheng_stylus_control.a'
        run([clang.with_name('llvm-ar'), 'rcs', control, *[backend/(name+'.o') for name in
            ('PenController', 'PenHardware', 'PenHidEndpoint', 'PenLeaseJournal')]], 'archive-controller')
        intermediate = rom/'out/soong/.intermediates/device/xiaomi/sheng/interfaces/input/stylus'
        library_name = 'vendor.lineage.sheng.stylus-V1-ndk.so'
        library = target('vendor/lib64/'+library_name)
        daemon_name = 'vendor.lineage.sheng.stylus-service'
        daemon = target('vendor/bin/hw/'+daemon_name)
        receipt['link_inputs_sha256'] = {}
        for kind, module, name, output in (('ndk', library_name.removesuffix('.so'), library_name, library),
                                           ('service', daemon_name, daemon_name, daemon)):
            responses = list((intermediate/module).glob('*/unstripped/'+name+'.rsp'))
            assert len(responses) == 1
            response = []
            for value in shlex.split(responses[0].read_text()):
                base = Path(value).name
                if base == 'IPenController.o': value = str(work/'IPenController.o')
                elif base == 'PenControllerService.o': value = str(backend/'PenControllerService.o')
                elif base == control.name: value = str(control)
                elif base == library_name: value = str(library)
                if not value.startswith('-'):
                    receipt['link_inputs_sha256'][value] = sha(rom/value)
                response.append(value)
            receipt['link_inputs_sha256'][str(responses[0])] = sha(responses[0])
            rsp = work/(kind+'.rsp')
            rsp.write_text(shlex.join(response)+'\n')
            command = [x for x in common_link]
            command[next(i for i,x in enumerate(command) if x.startswith('@'))] = '@'+str(rsp)
            command[command.index('-o')+1] = str(work/(name+'.unstripped'))
            command = ['aarch64-linux-android35' if x.startswith('aarch64-linux-android') else x for x in command]
            if kind == 'ndk':
                command = [x for x in command if x not in ('-pie', '-Wl,-dynamic-linker,/system/bin/linker64')]
                command = [x.replace('crtbegin_dynamic/', 'crtbegin_so/').replace('/crtbegin_dynamic.o', '/crtbegin_so.o')
                    .replace('crtend_android/', 'crtend_so/').replace('/crtend_android.o', '/crtend_so.o') for x in command]
                command += ['-shared', '-Wl,-soname,'+library_name]
            run(command, 'link-'+kind)
            run([clang.with_name('llvm-strip'), '--strip-debug', '-o', output, work/(name+'.unstripped')], 'strip-'+kind)
            elf = run([clang.with_name('llvm-readelf'), '-h', '-d', output], 'elf-'+kind)
            assert 'AArch64' in elf
            print('Linked '+name, flush=True)
        assert prior['frozen_api_hash'].encode() in library.read_bytes()
        classes_jar = work/'classes.jar'
        with zipfile.ZipFile(classes_jar, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted((backend/'java-classes').rglob('*.class')):
                archive.write(path, path.relative_to(backend/'java-classes').as_posix())
        jdk = rom/'prebuilts/jdk/jdk21/linux-x86/bin'
        sdk = rom/'prebuilts/sdk/37.0/public/android.jar'
        dex = work/'dex'; dex.mkdir()
        command = [jdk/'java', '-Xmx512m', '-cp', rom/'prebuilts/r8/r8.jar', 'com.android.tools.r8.D8',
            '--release', '--lib', sdk, '--min-api', '35', '--output', dex]
        for path in prior['classpath_sha256']: command += ['--classpath', path]
        run([*command, classes_jar], 'dex')
        resource_apk = work/'resources.apk'
        run([host/'aapt2', 'link', '-I', sdk, '--manifest', source/'AndroidManifest.xml',
            '--min-sdk-version', '35', '--target-sdk-version', '37', '-o', resource_apk], 'manifest-resources')
        unsigned = work/'unsigned.apk'
        with zipfile.ZipFile(resource_apk) as original, zipfile.ZipFile(unsigned, 'w') as output:
            for entry in original.infolist(): output.writestr(entry, original.read(entry.filename))
            for path in sorted(dex.glob('*.dex')): output.write(path, path.name, compress_type=zipfile.ZIP_STORED)
        aligned = work/'aligned.apk'
        run([host/'zipalign', '-P', '16', '-f', '4', unsigned, aligned], 'align')
        apk = target('product/priv-app/ShengStylus/ShengStylus.apk')
        security = rom/'build/target/product/security'
        signer = rom/'prebuilts/sdk/tools/linux/lib/apksigner.jar'
        run([jdk/'java', '-Xmx256m', '-jar', signer, 'sign', '--key', security/'platform.pk8',
             '--cert', security/'platform.x509.pem', '--min-sdk-version', '35', '--out', apk, aligned], 'sign')
        run([jdk/'java', '-Xmx256m', '-jar', signer, 'verify', '--verbose', '--print-certs', apk], 'signature')
        run([host/'zipalign', '-c', '-P', '16', '4', apk], 'verify-alignment')
        shutil.copyfile(source/'native'/('vendor.lineage.sheng.stylus-service.rc'), target('vendor/etc/init/vendor.lineage.sheng.stylus-service.rc'))
        shutil.copyfile(source/'privapp-permissions-org.lineageos.sheng.stylus.xml', target('product/etc/permissions/privapp-permissions-org.lineageos.sheng.stylus.xml'))
        native_test = workspace/'reports/device/20261114-stylus-service/native-control-test-p9dooiyv'
        test_receipt = json.loads((native_test/'receipt.json').read_text())
        for path, expected in test_receipt['actual_source_sha256'].items(): assert sha(Path(path)) == expected
        assertions = controller_assertion_count(run([native_test/'controller-test'], 'controller-test'))
        assert sources == source_hashes_for_guard(workspace, rom, args.snapshot_guard)
        receipt.update(passed=True, targeted_modules_linked=True, policy_vintf_qualified=False,
            apk_sha256=sha(apk), service_sha256=sha(daemon), library_sha256=sha(library),
            host_assertions=assertions, host_test_binary=str(native_test/'controller-test'),
            host_test_binary_sha256=sha(native_test/'controller-test'),
            retained_link_receipt=str(retained_path), retained_link_receipt_sha256=sha(retained_path))
        print('APK and native modules complete; '+str(assertions)+' controller assertions passed. Policy/VINTF qualification follows.', flush=True)
    except BaseException as error:
        receipt['error'] = repr(error)
        raise
    finally:
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        save()
    print(str(work/'build-receipt.json'))


if __name__ == '__main__':
    main()
