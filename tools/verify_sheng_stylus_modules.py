#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify normally built stylus artifacts; never install or claim hardware acceptance."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from sheng_stylus_evidence import controller_assertion_count, source_hashes_for_guard, qualified_build_record

parser = argparse.ArgumentParser()
parser.add_argument('--guard', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
workspace = Path(__file__).resolve().parents[4]
rom = Path('/root/sheng-lineage/lineage-24.0')
product = rom/'out/target/product/sheng'
host = rom/'out/host/linux-x86/bin'
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=False)
guard = json.loads(args.guard.read_text())
receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), passed=False,
               normal_module_build_passed=False, api_frozen=False,
               installed=False, hardware_tested=False, full_product_build_passed=False)
commands = []
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
environment = dict(os.environ, LANG='C.UTF-8', LC_ALL='C.UTF-8',
                   LD_LIBRARY_PATH=str(host.parent/'lib64'))

def run(argv, filename):
    env = dict(environment)
    if Path(argv[0]).name == 'java': env.pop('LD_LIBRARY_PATH', None)
    result = subprocess.run(list(map(str, argv)), cwd=rom, env=env,
                            capture_output=True, text=True, timeout=180)
    (output/filename).write_text(result.stdout+result.stderr)
    commands.append(dict(argv=list(map(str, argv)), exit_code=result.returncode, output=filename))
    (output/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
    if result.returncode: raise RuntimeError(filename+' failed: '+result.stderr[-1500:])
    return result.stdout+result.stderr

try:
    guard = qualified_build_record(args.guard, workspace, rom)
    targeted = guard['targeted_module_build_passed']
    product = Path(guard['product_root'])
    required_targets = ['ShengStylus', 'vendor.lineage.sheng.stylus-service',
                        'sheng_stylus_control_test', 'selinux_policy',
                        'framework_compatibility_matrix.device.xml']
    if not targeted:
        targets = guard['command'][2:]
        assert targets == required_targets or targets == required_targets + [
            'sheng-qti-codec2-bootstrap', 'libsheng_qti_codec2_service']
    work = Path(guard['build_work'])
    if not targeted:
        assert '#### build completed successfully' in (work/'build.log').read_text()
    audit = json.loads((work/'postbuild-upstream-audit.json').read_text())
    assert audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']
    source_hashes = source_hashes_for_guard(workspace, rom, args.guard)
    run(['python3', workspace/'device/xiaomi/sheng/tools/verify_device_source_mirror.py',
         '--workspace', workspace, '--rom', rom, '--path', 'interfaces/input/stylus',
         '--path', 'configs/vintf/framework_stylus_matrix.xml', '--reject-extra',
         '--output', output/'source-mirror.json'], 'source-mirror.log')
    apk = product/'product/priv-app/ShengStylus/ShengStylus.apk'
    badging = run([host/'aapt2', 'dump', 'badging', apk], 'badging.txt')
    assert "package: name='org.lineageos.sheng.stylus' versionCode='1' versionName='1.0'" in badging
    assert re.search(r"^(?:minSdkVersion|sdkVersion):'35'$", badging, re.MULTILINE)
    assert re.search(r"^targetSdkVersion:'37'$", badging, re.MULTILINE)
    manifest = run([host/'aapt2', 'dump', 'xmltree', apk, '--file', 'AndroidManifest.xml'], 'manifest.txt')
    for attribute in ('persistent', 'directBootAware'):
        assert re.search(r'A: (?:android|http://schemas\.android\.com/apk/res/android):'
            + attribute + r'\(0x[0-9a-f]+\)=(?:true|\(type 0x12\)0xffffffff)\s*$', manifest, re.MULTILINE)
    assert 'ShengStylusApplication' in manifest and 'android.uid.system' in manifest
    signature = run([rom/'prebuilts/jdk/jdk21/linux-x86/bin/java', '-jar',
        rom/'prebuilts/sdk/tools/linux/lib/apksigner.jar', 'verify', '--verbose',
        '--print-certs', '--min-sdk-version', '35', apk], 'signature.txt')
    certificate = re.search(r'certificate SHA-256 digest: ([0-9a-f]+)', signature).group(1)
    pem = (rom/'build/target/product/security/platform.x509.pem').read_text()
    assert certificate == hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()
    run([host/'zipalign', '-c', '-P', '16', '4', apk], 'zipalign.txt')
    with zipfile.ZipFile(apk) as archive:
        dex = {name: hashlib.sha256(archive.read(name)).hexdigest()
               for name in archive.namelist() if name.endswith('.dex')}
        assert dex and all(archive.read(name).startswith(b'dex\n') for name in dex)
    service = product/'vendor/bin/hw/vendor.lineage.sheng.stylus-service'
    elf = run(['/usr/bin/readelf', '-h', '-d', service], 'elf.txt')
    assert 'AArch64' in elf
    needed = re.findall(r'\(NEEDED\).*?\[(.*?)\]', elf)
    assert {'libbinder_ndk.so', 'libbase.so', 'vendor.lineage.sheng.stylus-V1-ndk.so'} <= set(needed)
    dependency_hashes = {}
    for name in needed:
        candidates = [product/base/name for base in ('vendor/lib64', 'system/lib64')]
        match = next((path for path in candidates if path.is_file()), None)
        if match is not None: dependency_hashes[name] = sha(match)
    test = Path(guard['host_test_binary']) if targeted else rom/'out/host/linux-x86/nativetest64/sheng_stylus_control_test/sheng_stylus_control_test'
    if targeted: assert sha(test) == guard['host_test_binary_sha256']
    tests = run([test], 'host-test.txt')
    host_assertions = controller_assertion_count(tests)
    precompiled = [product/partition/'etc/selinux/precompiled_sepolicy'
                   for partition in ('odm', 'vendor')]
    precompiled = [path for path in precompiled if path.is_file()]
    assert len(precompiled) == 1, 'Expected one installed precompiled policy'
    precompiled_path = str(precompiled[0].relative_to(product))
    policy_paths = [precompiled_path,
        'vendor/etc/selinux/vendor_sepolicy.cil', 'vendor/etc/selinux/vendor_file_contexts',
        'vendor/etc/selinux/vendor_service_contexts',
        'system_ext/etc/selinux/system_ext_sepolicy.cil',
        'system_ext/etc/selinux/system_ext_seapp_contexts']
    policy_hashes = {name: sha(product/name) for name in policy_paths}
    contexts = (product/'vendor/etc/selinux/vendor_service_contexts').read_text()
    assert 'vendor.lineage.sheng.stylus.IPenController/default' in contexts
    assert 'hal_sheng_stylus_service' in contexts
    app_contexts = (product/'system_ext/etc/selinux/system_ext_seapp_contexts').read_text()
    assert 'name=org.lineageos.sheng.stylus' in app_contexts and 'domain=sheng_stylus_app' in app_contexts
    rc = product/'vendor/etc/init/vendor.lineage.sheng.stylus-service.rc'
    fragment = product/'vendor/etc/vintf/manifest/vendor.lineage.sheng.stylus-service.xml'
    permission = product/'product/etc/permissions/privapp-permissions-org.lineageos.sheng.stylus.xml'
    assert rc.read_bytes() == (rom/'device/xiaomi/sheng/interfaces/input/stylus/native'/rc.name).read_bytes()
    installed_manifest = ET.fromstring(fragment.read_bytes())
    assert installed_manifest.tag == 'manifest' and installed_manifest.get('type') == 'device'
    hals = installed_manifest.findall('hal')
    assert len(hals) == 1, 'The frozen stylus HAL must remain in the assembled VINTF fragment'
    hal = hals[0]
    assert hal.get('format') == 'aidl'
    assert hal.findtext('name') == 'vendor.lineage.sheng.stylus'
    assert [item.text for item in hal.findall('version')] == ['1']
    instances = [item.text for item in hal.findall('fqname')]
    instances += [interface.findtext('name') + '/' + instance.text
                  for interface in hal.findall('interface') for instance in interface.findall('instance')]
    assert instances == ['IPenController/default']
    matrix_path = product/'system/etc/vintf/compatibility_matrix.device.xml'
    matrix = ET.fromstring(matrix_path.read_bytes())
    assert matrix.tag == 'compatibility-matrix' and matrix.get('type') == 'framework'
    control = [hal for hal in matrix.findall('hal')
               if hal.findtext('name') == 'vendor.lineage.sheng.stylus']
    assert len(control) == 1 and control[0].get('format') == 'aidl'
    assert control[0].findtext('version') == '1'
    assert control[0].findtext('interface/name') == 'IPenController'
    assert control[0].findtext('interface/instance') == 'default'
    api = rom/'device/xiaomi/sheng/interfaces/input/stylus'
    assert re.search(r'\bfrozen:\s*true\s*,', (api/'Android.bp').read_text())
    frozen_hash = (api/'aidl_api/vendor.lineage.sheng.stylus/1/.hash').read_text().strip()
    assert re.fullmatch(r'[0-9a-f]{40}', frozen_hash)
    aidl_library = product/'vendor/lib64/vendor.lineage.sheng.stylus-V1-ndk.so'
    assert frozen_hash.encode() in aidl_library.read_bytes(), 'The installed NDK interface must use the frozen hash'
    assert permission.read_bytes() == (rom/'device/xiaomi/sheng/interfaces/input/stylus'/permission.name).read_bytes()
    receipt.update(passed=True, normal_module_build_passed=not targeted,
        qualified_module_build_passed=True, targeted_module_build_passed=targeted, api_frozen=True,
        frozen_api_version=1, frozen_api_hash=frozen_hash, vintf_instance='IPenController/default',
        platform_certificate_verified=True,
        apk_sha256=sha(apk), dex_sha256=dex, service_sha256=sha(service),
        elf_needed=needed, dependency_sha256=dependency_hashes,
        policy_sha256=policy_hashes, precompiled_policy_path=precompiled_path,
        init_rc_sha256=sha(rc), vintf_fragment_sha256=sha(fragment),
        framework_matrix_sha256=sha(matrix_path),
        privileged_permissions_sha256=sha(permission), host_assertions=host_assertions,
        source_sha256=source_hashes,
        source_sync_sha256=sha(args.guard.parent/'stylus-source-sync.json'),
        swap_receipt_sha256=sha(args.guard.parent/'swap-priority.json'),
        guard_sha256=sha(args.guard), postbuild_audit_sha256=sha(work/'postbuild-upstream-audit.json'))
except BaseException as error:
    receipt['error'] = repr(error)
    raise
finally:
    (output/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
print(json.dumps(receipt, indent=2))
