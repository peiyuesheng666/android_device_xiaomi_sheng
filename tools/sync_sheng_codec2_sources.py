#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Mirror device-owned Codec2 sources and refresh their sole vendor installers."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import re

from audit_sheng_product_apps import audit
from build_sheng_qti_bootstrap_candidate import PROFILES, SOURCES, sha
from postprocess_vendor import install_qti_audio_bootstrap, install_qti_bootstrap


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rom = args.rom.resolve(strict=True)
    source = Path(__file__).resolve().parents[1]
    target = rom / 'device/xiaomi/sheng'
    work = args.output.resolve()
    work.mkdir(parents=True, exist_ok=False)
    lock = (rom / 'out/.sheng-device-modules.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    product_before = audit(target)
    assert product_before == audit(source)
    selected = {'interfaces/compat/codec2/' + name for name in (*SOURCES, 'README-qti.md')}
    selected.update('tools/' + name for name in (
        'build_sheng_qti_bootstrap_candidate.py', 'run_sheng_qti_bootstrap_candidate.py',
        'record_sheng_qti_bootstrap_build.py', 'prepare_sheng_qti_bootstrap_installer.py',
        'prepare_sheng_pen_settings_product.py', 'build_sheng_pen_settings_product.sh',
        'postprocess_vendor.py', 'prepare_sheng_audio_backends.py', 'sync_sheng_codec2_sources.py',
        'package_sheng_codec2_service.py', 'flash_sheng_codec2_service.py', 'verify_sheng_qti_service_elf.py',
        'build_sheng_codec2_roundtrip.py', 'ShengCodec2RoundTrip.java', 'ShengAudioCodec2RoundTrip.java',
        'ShengLosslessAudioFileProbe.java',
        'run_sheng_audio_file_roundtrip.py', 'test_sheng_alac_config.cpp',
        'qti_pool_bootstrap.cpp', 'qti_pool_payload.cpp', 'run_sheng_qti_pool_probe.py'))
    selected.update(('configs/audio-codec-backends.json', 'proprietary-files.txt',
                     'docs/DEVICE_TREE_COMPLETION_GOAL.md', 'docs/HARDWARE_STATUS.md', 'docs/SOURCE_POLICY.md'))
    receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), passed=False,
                   ninja_graph_loaded=False, files={}, generated_vendor={}, original_services={})

    def write(path, data, relative):
        assert path.resolve().is_relative_to(rom) and not path.is_symlink()
        before = path.read_bytes() if path.exists() else None
        if before != data:
            if before is not None:
                backup = work / 'before' / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(before)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        assert path.read_bytes() == data
        receipt['files'][relative] = dict(sha256=sha(path), changed=before != data)

    try:
        for relative in sorted(selected):
            write(target / relative, (source / relative).read_bytes(), 'device/xiaomi/sheng/' + relative)
        vendor = rom / 'vendor/xiaomi/sheng'
        bp = vendor / 'Android.bp'
        before = bp.read_text()
        proposed = install_qti_audio_bootstrap(install_qti_bootstrap(before))
        assert install_qti_audio_bootstrap(install_qti_bootstrap(proposed)) == proposed

        def other_modules(text):
            for profile in PROFILES.values():
                marker = '    name: "' + profile['service'] + '",'
                assert text.count(marker) == 1
                start = text.index(marker)
                end = text.index('\n}\n', start) + 3
                text = text[:start] + text[end:]
            return text

        assert other_modules(before) == other_modules(proposed)
        for profile in PROFILES.values():
            original = vendor / 'proprietary/vendor/bin/hw' / profile['service']
            receipt['original_services'][profile['service']] = sha(original)
            marker = '    name: "' + profile['service'] + '",'
            start = proposed.index(marker)
            section = proposed[start:proposed.index('\n}\n', start)]
            assert '":' + profile['bootstrap'] + '"' in section
            assert 'required: ["' + profile['payload'].removesuffix('.so') + '"]' in section
        catalog = json.loads((source / 'configs/audio-codec-backends.json').read_text())
        for item in catalog['libraries']:
            assert sha(vendor / 'proprietary/vendor' / item['path']) == item['sha256']
            assert proposed.count('    name: "' + item['module'] + '",') == 1
            assert re.search(r'^(?:    |PRODUCT_PACKAGES \+= )' + re.escape(item['module']) + r'(?: \\)?$',
                             (vendor / 'sheng-vendor.mk').read_text(), re.M)
        write(bp, proposed.encode(), 'vendor/xiaomi/sheng/Android.bp')
        assert audit(target) == product_before == audit(source)
        receipt.update(passed=True, product_layout_preserved=True, unrelated_vendor_modules_preserved=True)
        receipt['generated_vendor'] = dict(path=str(bp), sha256=sha(bp), idempotent=True)
    except BaseException as error:
        receipt['error'] = repr(error)
        raise
    finally:
        (work / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(dict(passed=True, file_count=len(receipt['files']), product_layout_preserved=True)))


if __name__ == '__main__':
    main()
