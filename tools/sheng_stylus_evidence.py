#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read-only source and test-result checks shared by stylus qualification tools."""
import hashlib
import json
from pathlib import Path
import re


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes_for_guard(workspace, rom, guard):
    source = workspace/'device/xiaomi/sheng'
    mirror = rom/'device/xiaomi/sheng'
    sync = json.loads((guard.parent/'stylus-source-sync.json').read_text())
    if sync.get('product_packages_enabled') is not True:
        raise ValueError('Build snapshot did not enable the stylus product packages')
    prefix = 'interfaces/input/stylus/'
    matrix = 'configs/vintf/framework_stylus_matrix.xml'
    recorded = {name: item['sha256'] for name, item in sync['files'].items()
                if name.startswith(prefix) or name == matrix}
    required = {prefix+'Android.bp', prefix+'AndroidManifest.xml',
                prefix+'native/PenController.cpp', prefix+'tests/PenControllerTest.cpp', matrix}
    if not required <= recorded.keys():
        raise ValueError('Build snapshot lacks required stylus inputs')
    board_lines = (
        'SYSTEM_EXT_PUBLIC_SEPOLICY_DIRS += $(DEVICE_PATH)/interfaces/input/stylus/sepolicy/system_ext/public',
        'SYSTEM_EXT_PRIVATE_SEPOLICY_DIRS += $(DEVICE_PATH)/interfaces/input/stylus/sepolicy/system_ext/private',
        'BOARD_VENDOR_SEPOLICY_DIRS += $(DEVICE_PATH)/interfaces/input/stylus/sepolicy/vendor',
    )
    for root in (source, mirror):
        current = {path.relative_to(root).as_posix()
                   for path in (root/prefix).rglob('*') if path.is_file()} | {matrix}
        if current != recorded.keys():
            raise ValueError('Stylus source inventory differs from the build snapshot: '+str(root))
        for name, digest in recorded.items():
            if sha(root/name) != digest:
                raise ValueError('Stylus source changed after this build: '+name)
        declaration = 'PRODUCT_PACKAGES += ShengStylus vendor.lineage.sheng.stylus-service'
        if declaration not in (root/'device.mk').read_text().splitlines():
            raise ValueError('Current product no longer enables the stylus packages')
        # The enclosing wrapper may subsequently mirror independent Recovery
        # declarations. Validate the stylus configuration without requiring
        # unrelated product text to match this earlier scoped sync snapshot.
        board = (root/'BoardConfig.mk').read_text()
        if (any(line not in board.splitlines() for line in board_lines)
                or '$(DEVICE_PATH)/'+matrix not in board):
            raise ValueError('Current board lacks required stylus policy or matrix declarations')
    return recorded


def controller_assertion_count(output):
    match = re.fullmatch(r'PASS assertions=([1-9][0-9]*): [^\r\n]+\r?\n?', output)
    if match is None:
        raise ValueError('Native controller test did not report a complete passing result')
    return int(match.group(1))


def qualified_build_record(path, workspace, rom):
    """Accept actual normal builds or fully evidenced targeted module outputs."""
    build = json.loads(path.read_text())
    if build.get('kind') != 'targeted-stylus-link-and-apk':
        if not (build.get('exit_code') == 0 and build.get('normal_module_build_passed') is True
                and build.get('compiler_restored') is True
                and build.get('module_status', {}).get('postbuild_checks_completed') is True):
            raise ValueError('No successful qualified module build')
        return dict(build, qualified_module_build_passed=True, targeted_module_build_passed=False,
                    product_root=str(rom/'out/target/product/sheng'))
    if not (build.get('passed') is True and build.get('targeted_modules_linked') is True
            and build.get('normal_module_build_passed') is False and build.get('ninja_graph_loaded') is False
            and build.get('compiler_restored') is True and build.get('frozen_api_version') == 1
            and build.get('commands') and all(item['exit_code'] == 0 for item in build['commands'])):
        raise ValueError('Targeted compilation/link evidence is incomplete')
    backend = Path(build['backend_receipt'])
    if sha(backend) != build['backend_receipt_sha256']:
        raise ValueError('Targeted backend compilation evidence changed')
    proof = json.loads((path.parent/'policy-vintf-receipt.json').read_text())
    if not (proof.get('passed') is True and proof.get('complete_policy_recompiled') is True
            and proof.get('neverallows_enabled') is True and proof.get('frozen_vintf_assembled') is True
            and proof.get('other_baseline_matrix_requirements_preserved') is True
            and proof.get('targeted_build_receipt_sha256') == sha(path)
            and all(item['exit_code'] == 0 for item in proof['commands'])):
        raise ValueError('Targeted policy or frozen VINTF evidence is incomplete')
    product = Path(build['product_root']).resolve(strict=True)
    if product != path.parent.resolve()/'product':
        raise ValueError('Unexpected targeted product directory')
    files = {file.relative_to(product).as_posix() for file in product.rglob('*') if file.is_file()}
    if files != proof['outputs_sha256'].keys():
        raise ValueError('Targeted output inventory changed')
    for name, digest in proof['outputs_sha256'].items():
        if sha(product/name) != digest:
            raise ValueError('Targeted output changed: '+name)
    for name, digest in proof['inputs_sha256'].items():
        if sha(Path(name)) != digest:
            raise ValueError('Targeted policy input changed: '+name)
    for name, digest in build['link_inputs_sha256'].items():
        if sha(rom/name) != digest:
            raise ValueError('Targeted linker input changed: '+name)
    if (source_hashes_for_guard(workspace, rom, path) != build['source_sha256']
            or sha(path.parent/'stylus-source-sync.json') != build['source_sync_sha256']):
        raise ValueError('Targeted source snapshot changed')
    audit = json.loads((path.parent/'postbuild-upstream-audit.json').read_text())
    if not (audit['known_public_sources_passed'] and not audit['all_project_nonclean_status']):
        raise ValueError('Targeted upstream source audit failed')
    swap = json.loads((path.parent/'swap-priority.json').read_text())
    if not (swap['complete'] and swap['policy'] == 'C-only' and swap['e_drive_swap_allowed'] is False):
        raise ValueError('Targeted build violated the C-only swap requirement')
    return dict(build, qualified_module_build_passed=True, targeted_module_build_passed=True,
                swap_policy=swap, build_work=str(path.parent))
