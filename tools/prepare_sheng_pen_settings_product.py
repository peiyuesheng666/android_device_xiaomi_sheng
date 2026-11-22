#!/usr/bin/env python3
"""Mirror the pen page and optional Recovery inputs without replacing a product."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, default=Path('/root/sheng-lineage/lineage-24.0'))
    parser.add_argument('--work', type=Path)
    parser.add_argument('--include-recovery', action='store_true')
    parser.add_argument('--include-media-sensors', action='store_true',
                        help='Also mirror the QTI Codec2 and sensor/thermal batch inputs')
    parser.add_argument('--qti-bootstrap-build', type=Path)
    parser.add_argument('--qti-bootstrap-runtime', type=Path)
    parser.add_argument('--build-lock-fd', type=int,
                        help='Inherit the enclosing build wrapper output lock for QTI selection')
    args = parser.parse_args()
    if bool(args.qti_bootstrap_build) != bool(args.qti_bootstrap_runtime):
        parser.error('QTI selection requires both qualified build and runtime receipts')
    if args.qti_bootstrap_build and not args.include_media_sensors:
        parser.error('QTI selection requires the media source mirror and verification scope')
    if args.build_lock_fd is not None and not args.qti_bootstrap_build:
        parser.error('An inherited selection lock requires an explicit QTI candidate')
    target = args.rom.resolve(strict=True) / 'device/xiaomi/sheng'
    qti_evidence = None
    qti_lock = None
    if args.qti_bootstrap_build:
        from prepare_sheng_qti_bootstrap_installer import acquire_output_lock, installer, qualify
        qti_lock = acquire_output_lock(args.rom.resolve(strict=True), args.build_lock_fd)
        args.qti_bootstrap_build = args.qti_bootstrap_build.resolve(strict=True)
        args.qti_bootstrap_runtime = args.qti_bootstrap_runtime.resolve(strict=True)
        # Reject stale/unqualified candidates before any source or vendor write.
        qti_evidence = qualify(args.qti_bootstrap_build, args.qti_bootstrap_runtime,
                               args.rom.resolve(strict=True), SOURCE / 'interfaces/compat/codec2')
    if args.work is None:
        parent = Path('/root/sheng-lineage/hardware-diagnostics/sheng-pen-settings-20261112')
        parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix='source-sync-', dir=parent))
    else:
        work = args.work.resolve()
        work.mkdir(parents=True, exist_ok=True)
    receipt = {'date_utc': datetime.now(timezone.utc).isoformat(),
               'scope': 'pen page, touch runtime and Recovery' if args.include_recovery else 'pen page and touch runtime',
               'work': str(work), 'files': {}, 'declarations': {}}
    if args.include_media_sensors:
        receipt['scope'] += ', QTI Codec2 and sensor/thermal configuration'

    def write_owned(relative, data):
        dst = target / relative
        before = dst.read_bytes() if dst.exists() else None
        if before != data:
            if before is not None:
                backup = work / 'source-backup' / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                if not backup.exists():
                    backup.write_bytes(before)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            shutil.copymode(SOURCE / relative, dst)
        receipt['files'][relative.as_posix()] = {
            'sha256': sha(data), 'changed': before != data,
            'before_sha256': sha(before) if before is not None else None}

    # Compare against this invocation, never the first session's product backup.
    product = target / 'device.mk'
    product_before = product.read_bytes()
    product_text = product_before.decode('utf-8')
    newline = '\r\n' if '\r\n' in product_text else '\n'
    pen_line = 'PRODUCT_PACKAGES += ShengPenSettings'
    assert pen_line in (SOURCE / 'device.mk').read_text(), 'Missing source package declaration'
    if pen_line not in product_text.splitlines():
        assert 'ShengPenSettings' not in product_text, 'Review the existing pen declaration'
        product_text += ('' if product_text.endswith('\n') else newline) + newline
        product_text += ('# Independent pen connection, battery and firmware information page.'
                         + newline + pen_line + newline)

    touch_copy = '    $(LOCAL_PATH)/configs/touch/sheng-touch-report:$(TARGET_COPY_OUT_VENDOR)/bin/sheng-touch-report \\'
    if touch_copy in product_text.splitlines():
        product_text = product_text.replace(touch_copy + newline, '', 1)
    assert 'configs/touch/sheng-touch-report:' not in product_text, 'Review unknown touch ELF copy assignment'
    touch_line = 'PRODUCT_PACKAGES += sheng-touch-report'
    assert touch_line in (SOURCE / 'device.mk').read_text().splitlines()
    if touch_line not in product_text.splitlines():
        product_text += ('' if product_text.endswith('\n') else newline) + newline + touch_line + newline
    # Append only this module; preserve all other accepted root declarations.
    marker = '// Keep the accepted THP executable byte-identical and use the normal ELF installer.'
    source_blueprint = (SOURCE / 'Android.bp').read_text()
    touch_block = source_blueprint[source_blueprint.index(marker):].strip() + '\n'
    blueprint = target / 'Android.bp'
    blueprint_before = blueprint.read_bytes()
    blueprint_text = blueprint_before.decode('utf-8')
    if marker in blueprint_text:
        existing = blueprint_text[blueprint_text.index(marker):].replace('\r\n', '\n').strip() + '\n'
        assert existing == touch_block, 'Review the existing touch runtime module'
    else:
        assert 'name: "sheng-touch-report"' not in blueprint_text, 'Review duplicate touch runtime installer'
        blueprint_text += ('' if blueprint_text.endswith('\n') else newline) + newline
        blueprint_text += touch_block.replace('\n', newline)
    write_owned(Path('Android.bp'), blueprint_text.encode('utf-8'))
    write_owned(Path('configs/touch/sheng-touch-report'), (SOURCE / 'configs/touch/sheng-touch-report').read_bytes())
    # Keep the nested kernel build's unchanged-output semantics in device-owned
    # Make rules. Do not overwrite another root Makefile's module declarations.
    kernel_make = target / 'Android.mk'
    source_make = (SOURCE / 'Android.mk').read_text()
    kernel_marker = '# The nested kernel build can validate an unchanged Image after Kconfig or'
    kernel_block = source_make[source_make.index(kernel_marker):].split('\n\n', 1)[0].rstrip('\n')
    if kernel_make.exists():
        make_text = kernel_make.read_text()
        if kernel_marker in make_text:
            existing = make_text[make_text.index(kernel_marker):].split('\n\n', 1)[0].rstrip('\n')
            assert existing == kernel_block, 'Review the existing kernel restat rule'
        else:
            make_text += ('' if make_text.endswith('\n') else '\n') + '\n' + kernel_block + '\n'
    else:
        make_text = source_make
    write_owned(Path('Android.mk'), make_text.encode('utf-8'))
    receipt['declarations']['Android.bp'] = {
        'before_sha256': sha(blueprint_before), 'after_sha256': sha(blueprint_text.encode('utf-8')),
        'other_module_declarations_preserved': True}

    # Keep the complete accepted Recovery source set together. In particular,
    # genfs_contexts already refers to the firmware-path type in file.te; a
    # mirror that copies only the label cannot compile the Recovery policy.
    recovery_files = [str(path.relative_to(SOURCE)) for path in
                      sorted((SOURCE / 'rootdir/recovery').rglob('*')) if path.is_file()]
    recovery_files += [
        'proprietary-files.txt',
        'rootdir/etc/init.recovery.qcom.rc',
        'sepolicy/vendor/file.te', 'sepolicy/vendor/init.te',
        'sepolicy/vendor/genfs_contexts',
        'configs/modules/modules.list.boot', 'configs/modules/modules.load.first_stage',
        'configs/modules/modules.list.recovery', 'configs/modules/modules.load.recovery']
    board_before = None
    if args.include_recovery:
        marker = '# Recovery starts the optional oops logger after storage coldboot.'
        source_product = (SOURCE / 'device.mk').read_text()
        block = source_product[source_product.index(marker):].split('\n\n', 1)[0]
        if marker in product_text:
            existing = product_text[product_text.index(marker):].replace('\r\n', '\n').split('\n\n', 1)[0].rstrip('\n')
            # Upgrade only the previously shipped two-file copy block. Any
            # other local edits need review instead of being overwritten.
            old_block = '\n'.join(line for line in block.splitlines()
                                  if '/rootdir/recovery/hardware.sh:' not in line)
            assert existing in (block, old_block), 'Review the existing Recovery copy block'
            if existing != block:
                assert 'sheng-recovery-hardware' not in product_text, 'Review duplicate Recovery hardware destination'
                product_text = product_text.replace(existing.replace('\n', newline),
                                                    block.replace('\n', newline), 1)
        else:
            for destination in ('init.recovery.sheng-late-modules.rc', 'sheng-recovery-late-modules',
                                'sheng-recovery-hardware'):
                assert destination not in product_text, 'Review duplicate Recovery copy destinations'
            product_text += ('' if product_text.endswith('\n') else newline) + newline
            product_text += block.replace('\n', newline) + newline
        touch_marker = '# Recovery touch processing uses the same stock inputs as accepted r59.'
        touch_block = source_product[source_product.index(touch_marker):].split('\n\n', 1)[0]
        if touch_marker in product_text:
            existing = product_text[product_text.index(touch_marker):].replace('\r\n', '\n').split('\n\n', 1)[0].rstrip('\n')
            assert existing == touch_block, 'Review the existing Recovery touch block'
        else:
            assert 'sheng-recovery-touch-runtime' not in product_text, 'Review duplicate Recovery touch registration'
            product_text += ('' if product_text.endswith('\n') else newline) + newline
            product_text += touch_block.replace('\n', newline) + newline
        board = target / 'BoardConfig.mk'
        board_before = board.read_bytes()
        board_text = board_before.decode('utf-8')
        hook = 'TARGET_RECOVERY_UI_LIB := librecovery_ui_sheng'
        assert hook in (SOURCE / 'BoardConfig.mk').read_text().splitlines()
        if hook not in board_text.splitlines():
            assert 'TARGET_RECOVERY_UI_LIB' not in board_text, 'Review the existing Recovery UI hook'
            anchor = 'TARGET_RECOVERY_PIXEL_FORMAT := RGBX_8888'
            assert board_text.count(anchor) == 1, 'Recovery BoardConfig anchor is ambiguous'
            board_newline = '\r\n' if '\r\n' in board_text else '\n'
            board_text = board_text.replace(anchor, anchor + board_newline + hook, 1)
        # vendor_boot must package the union: first-stage qrng_dlkm is absent
        # from the Recovery list. Preserve unknown local assignments for review.
        old_boot = 'BOOT_KERNEL_MODULES := $(strip $(shell cat $(DEVICE_PATH)/configs/modules/modules.list.recovery))'
        new_boot = 'BOOT_KERNEL_MODULES := $(sort $(shell cat $(DEVICE_PATH)/configs/modules/modules.list.boot $(DEVICE_PATH)/configs/modules/modules.list.recovery))'
        assert new_boot in (SOURCE / 'BoardConfig.mk').read_text().splitlines()
        assignments = [line for line in board_text.splitlines() if line.startswith('BOOT_KERNEL_MODULES ')]
        assert assignments in ([old_boot], [new_boot]), 'Review the existing boot module packaging assignment'
        board_text = board_text.replace(old_boot, new_boot, 1)
        board_text = board_text.replace(
            '# overwritten by vendor_boot, so both ramdisks need the recovery dependency set.',
            '# overwritten by vendor_boot, so vendor_boot needs both dependency sets. The' +
            ('\r\n' if '\r\n' in board_text else '\n') +
            '# first-stage set includes qrng_dlkm, which is not in the Recovery set.', 1)
        board_after = board_text.encode('utf-8')

    pen_scope = Path('interfaces/input/pen')
    expected_pen_files = set()
    for src in sorted((SOURCE / pen_scope).rglob('*')):
        if src.is_file():
            relative = src.relative_to(SOURCE)
            expected_pen_files.add(relative)
            write_owned(relative, src.read_bytes())
    # A resource moved to drawable-v21 must not leave its old drawable XML in
    # the build tree alongside the API 1 PNG. Preserve every obsolete file
    # before removing it, and limit this reconciliation to the owned pen page.
    receipt['obsolete_pen_files'] = {}
    pen_target = target / pen_scope
    for stale in sorted(pen_target.rglob('*')):
        if not (stale.is_file() or stale.is_symlink()):
            continue
        relative = stale.relative_to(target)
        if relative in expected_pen_files:
            continue
        assert not stale.is_symlink(), 'Review unexpected symlinks before source reconciliation'
        assert stale.resolve(strict=True).is_relative_to(pen_target.resolve(strict=True))
        original = stale.read_bytes()
        backup = work / 'obsolete-source-backup' / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        assert not backup.exists(), 'Obsolete source backup must not be overwritten'
        shutil.copy2(stale, backup)
        assert backup.read_bytes() == original and stale.read_bytes() == original
        stale.unlink()
        receipt['obsolete_pen_files'][relative.as_posix()] = {
            'before_sha256': sha(original), 'backup': str(backup), 'backup_verified': True}
    if args.include_recovery:
        for name in recovery_files:
            write_owned(Path(name), (SOURCE / name).read_bytes())
        write_owned(Path('BoardConfig.mk'), board_after)
        receipt['declarations']['BoardConfig.mk'] = {
            'before_sha256': sha(board_before), 'after_sha256': sha(board_after),
            'recovery_declarations_updated': board_before != board_after}
    if args.include_media_sensors:
        for name in (
            'interfaces/compat/codec2/Android.bp',
            'interfaces/compat/codec2/qti_service.cpp',
            'interfaces/compat/codec2/qti_bootstrap.cpp',
            'interfaces/compat/codec2/qti_payload.cpp',
            'interfaces/compat/codec2/qti_load_groups.h',
            'interfaces/compat/codec2/qti_profile.h',
            'interfaces/compat/codec2/README-qti.md',
            'tools/postprocess_vendor.py',
            'properties/vendor.prop',
            'overlay/FrameworkResOverlaySheng/res/values/platform-defaults.xml',
            'rootdir/etc/init.sm8550.rc',
            'sepolicy/vendor/genfs_contexts',
        ):
            write_owned(Path(name), (SOURCE / name).read_bytes())
        vendor = args.rom.resolve(strict=True) / 'vendor/xiaomi/sheng'
        vendor_bp = vendor / 'Android.bp'
        vendor_before = vendor_bp.read_bytes()
        backup = work / 'source-backup/vendor/xiaomi/sheng/Android.bp'
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            backup.write_bytes(vendor_before)
        original = vendor / 'proprietary/vendor/bin/hw/vendor.qti.media.c2@1.0-service'
        original_sha = sha(original.read_bytes())
        subprocess.run([sys.executable, str(target / 'tools/postprocess_vendor.py'),
                        str(vendor)], check=True)
        if qti_evidence is not None:
            # Keep the explicitly qualified normal-build selection under the
            # same lock after refreshing the generated vendor declarations.
            qti_evidence = qualify(args.qti_bootstrap_build, args.qti_bootstrap_runtime,
                                   args.rom.resolve(strict=True), SOURCE / 'interfaces/compat/codec2')
            proposed = installer(vendor_bp.read_text(), qti_evidence, SOURCE / 'interfaces/compat/codec2')
            vendor_bp.write_text(proposed)
        assert sha(original.read_bytes()) == original_sha, 'Original QTI service changed'
        receipt['generated_vendor'] = {
            'before_sha256': sha(vendor_before),
            'after_sha256': sha(vendor_bp.read_bytes()),
            'original_qti_service_sha256': original_sha,
            'original_qti_service_unchanged': True,
            'qti_bootstrap_selected': True,
            'qti_audio_bootstrap_selected': True,
            'normal_build_qualification_supplied': qti_evidence is not None,
        }
        if qti_evidence is not None:
            receipt['generated_vendor']['qti_qualification'] = {
                'build': str(args.qti_bootstrap_build),
                'runtime': str(args.qti_bootstrap_runtime),
                'build_receipt_sha256': sha((args.qti_bootstrap_build / 'build.json').read_bytes()),
                'runtime_receipt_sha256': sha((args.qti_bootstrap_runtime / 'runtime.json').read_bytes()),
            }
    product_after = product_text.encode('utf-8')
    write_owned(Path('device.mk'), product_after)
    receipt['declarations']['device.mk'] = {
        'before_sha256': sha(product_before), 'after_sha256': sha(product_after),
        'other_product_lines_preserved': True}
    (work / 'source-sync.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(f'Mirrored {receipt["scope"]}: {work / "source-sync.json"}')
    if qti_lock is not None:
        qti_lock.close()


if __name__ == '__main__':
    main()
