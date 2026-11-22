#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Package a qualified APE extractor and codec selection over a sealed baseline."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from package_sheng_batch_helpers import merge_parent, publish_batch, sha, stage_erofs, stage_ext4
from package_sheng_model_followup import HOST, ROM, run


LIBRARY = 'lib64/extractors/libshengapeextractor.so'
WRAPPER = 'etc/media_codecs_c2_audio.xml'
BASE_XML = 'etc/media_codecs_c2_audio_base.xml'


def qualify(device, build_path, runtime_path, host_path):
    build = json.loads(build_path.read_text())
    runtime = json.loads(runtime_path.read_text())
    host = json.loads(host_path.read_text())
    assert build['passed'] and build['targeted_module_build_passed']
    assert not build['normal_module_build_passed'] and not build['ninja_graph_loaded']
    assert runtime['passed'] and runtime['services_and_boot_unchanged'] and runtime['temporary_files_removed']
    assert not any(runtime[k] for k in ('plugin_registered', 'flashed', 'playback_used', 'microphone_used'))
    assert runtime['build_receipt_sha256'] == sha(build_path)
    assert runtime['source_sha256'] == build['source_sha256']
    assert [r['seek_us'] for r in runtime['runs']] == [0, 30000000, 60186122]
    assert all(r['passed'] and r['pcm_sha256'] == r['expected_pcm_sha256'] and
               r['bytes'] == r['expected_bytes'] for r in runtime['runs'])
    assert host['passed'] and not host['ninja_graph_loaded']
    assert set(host['sanitizers']) == {'address', 'undefined'}
    for path, digest in host['source_sha256'].items():
        assert sha(device / 'interfaces/media/ape' / path) == digest
    for path, digest in build['source_sha256'].items():
        assert sha(device / path) == digest, path
    for path, digest in build['input_sha256'].items():
        assert sha(Path(path)) == digest, path
    for row in build['outputs'].values():
        assert sha(Path(row['path'])) == row['sha256']
    wrapper = ET.parse(device / 'configs/audio/media_codecs_c2_audio.xml').getroot()
    assert wrapper.tag == 'Included' and [e.tag for e in wrapper] == ['Include', 'Decoders']
    assert wrapper[0].attrib == {'href': 'media_codecs_c2_audio_base.xml'}
    assert [e.attrib for e in wrapper[1]] == [
        dict(name='c2.qti.ape.sw.decoder', type='audio/x-ape', update='true', enabled='false'),
        dict(name='c2.qti.ape.hw.decoder', type='audio/x-ape', update='true', rank='0')]
    assert all(e.tag == 'MediaCodec' and len(e) == 0 for e in wrapper[1])
    return build, runtime, host


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('build', 'runtime', 'host', 'baseline', 'work', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    device = Path(__file__).resolve().parents[1]
    workspace = device.parents[2]
    lock = (ROM / 'out/.sheng-device-modules.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    build, runtime, host = qualify(device, args.build, args.runtime, args.host)
    baseline_path = args.baseline.absolute()
    baseline_hash = sha(baseline_path)
    baseline = json.loads(baseline_path.read_text())
    assert baseline['complete_avb_chain_verified'] and baseline['stylus_native_service_unchanged']
    rows = baseline['files'] + baseline['unchanged_partition_files']
    assert len(rows) == 14 and len({r['partition'] for r in rows}) == 14
    chain = {r['partition']: Path(baseline['work_dir']) / 'complete-chain' / r['name'] for r in rows}
    for row in rows:
        assert chain[row['partition']].stat().st_size == row['bytes']
        assert sha(chain[row['partition']]) == row['sha256']
    contexts_input = Path(baseline['scoped_file_contexts'])
    assert sha(contexts_input) == baseline['scoped_file_contexts_sha256']
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    assert work.stat().st_dev == Path('/').stat().st_dev
    assert shutil.disk_usage(work).free > 6 * 1024**3
    contexts = work / 'file-contexts.txt'
    shutil.copyfile(contexts_input, contexts)
    original_xml = ROM / 'hardware/qcom-caf/sm8550/audio/primary-hal/configs/common/codec2/media_codecs_c2_audio.xml'
    original_digest = sha(original_xml)
    product = work / 'product'
    entries = {'system_ext': {}, 'vendor': {}}
    selected = [('system_ext', LIBRARY, Path(build['outputs']['libshengapeextractor.so']['path'])),
                ('vendor', WRAPPER, device / 'configs/audio/media_codecs_c2_audio.xml'),
                ('vendor', BASE_XML, original_xml)]
    for part, relative, path in selected:
        target = product / part / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        entries[part][relative] = dict(source=str(target), bytes=target.stat().st_size, sha256=sha(target))
    sources = dict(build['source_sha256'])
    for path in ('device.mk', 'configs/audio/media_codecs_c2_audio.xml',
                 'interfaces/media/ape/tests/ApeFileTest.cpp', 'tools/package_sheng_ape_extractor.py',
                 'tools/run_sheng_ape_extractor_probe.py', 'tools/flash_sheng_codec2_service.py'):
        sources[path] = sha(device / path)
    nodes = {LIBRARY: dict(uid=0, gid=0, mode=0o644, mtime_ns=1230768000 * 10**9,
                           selinux='u:object_r:system_lib_file:s0')}
    for relative in ('lib64', 'lib64/extractors'):
        result = subprocess.run(['debugfs', '-R', 'stat /' + relative, chain['system_ext']],
                                capture_output=True, text=True, check=True)
        if 'Inode:' not in result.stdout:
            assert 'File not found' in result.stderr
            nodes[relative] = dict(uid=0, gid=0, mode=0o755, mtime_ns=1230768000 * 10**9,
                                   selinux='u:object_r:system_lib_file:s0')
    sys.path.insert(0, str(ROM / 'external/avb'))
    import avbtool
    avb = avbtool.Avb()
    print('Adding the qualified extractor to system_ext; checking retained inode metadata.', flush=True)
    system_ext, ext_descriptor, ext_stage = stage_ext4('system_ext', chain['system_ext'],
        entries['system_ext'], nodes, work, avb, avbtool, None, source_product=product)
    print('Applying device codec selection; retaining the original base XML and vendor labels.', flush=True)
    vendor, vendor_descriptor, vendor_stage = stage_erofs('vendor', chain['vendor'], entries['vendor'],
        {BASE_XML: dict(uid=0, gid=0, mode=0o644, mtime_ns=1230768000 * 10**9,
                        selinux='u:object_r:vendor_configs_file:s0')}, work, avb, avbtool,
        source_product=product, file_contexts=contexts)
    assert vendor_stage['baseline_entries'][WRAPPER] == ('file', original_digest)
    outputs = dict(system_ext=system_ext, vendor=vendor,
                   vbmeta_system=work / 'vbmeta_system.img', vbmeta=work / 'vbmeta.img')
    merge_parent(avb, avbtool, chain['vbmeta_system'], [ext_descriptor],
                 outputs['vbmeta_system'], 'SHA256_RSA2048', work)
    merge_parent(avb, avbtool, chain['vbmeta'], [vendor_descriptor], outputs['vbmeta'], 'SHA256_RSA4096', work)
    complete = work / 'complete-chain'
    complete.mkdir()
    for part, path in chain.items():
        (complete / (part + '.img')).symlink_to(outputs.get(part, path).resolve())
    result = run([HOST / 'avbtool', 'verify_image', '--image', complete / 'vbmeta.img',
                  '--follow_chain_partitions'], capture_output=True, text=True)
    (work / 'avb-verification.log').write_text(result.stdout + result.stderr)
    qualify(device, args.build, args.runtime, args.host)
    assert sha(baseline_path) == baseline_hash and sha(original_xml) == original_digest
    assert sha(contexts) == baseline['scoped_file_contexts_sha256']
    assert all(sha(device / path) == digest for path, digest in sources.items())
    report = dict(kind='ape-extractor-update', date_utc=datetime.now(timezone.utc).isoformat(),
        baseline_manifest=baseline_path.relative_to(workspace).as_posix(), baseline_manifest_sha256=baseline_hash,
        baseline_partitions=rows, unchanged_partition_files=[r for r in rows if r['partition'] not in outputs],
        entries=entries, removals={}, partition_reports=dict(vendor=vendor_stage, system_ext=ext_stage),
        applications=baseline['applications'], product_apps_unchanged=True, source_sha256=sources,
        qualified_ape={name: dict(path=str(path.resolve()), sha256=sha(path)) for name, path in
                       [('build', args.build), ('runtime', args.runtime), ('host', args.host)]},
        upstream_xml=dict(path=str(original_xml), sha256=original_digest),
        scoped_file_contexts=str(contexts), scoped_file_contexts_sha256=sha(contexts),
        work_dir=str(work), complete_avb_chain_verified=True, partition_sizes_unchanged=True,
        policy_and_vintf_inputs_unchanged=True, native_service_unchanged=True,
        stylus_native_service_unchanged=True, systemui_unchanged=True,
        normal_module_build_passed=False, full_product_build_passed=False, ninja_graph_loaded=False,
        targeted_module_build_passed=True, targeted_native_validation_passed=True,
        installed=False, e_drive_swap_allowed=False, native_c_staging=True)
    publish_batch(args.output.resolve(), outputs, report)
    print(args.output / 'build-result.json', flush=True)


if __name__ == '__main__':
    main()
