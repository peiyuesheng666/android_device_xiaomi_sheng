#!/usr/bin/env python3
"""Offline policy-only repack of the qualified, currently installed USB pair."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installed-pair', type=Path, required=True)
    parser.add_argument('--policy-qualification', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[4]
    sys.path.insert(0, str(workspace / 'scripts'))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_sheng_fastbootd_cold_trace import sha, digest, parse_cpio
    from package_sheng_recovery_modules import replace_records
    from build_sheng_recovery_usb_property_policy import CONTEXT, PROPERTY, source_contract
    source_contract(Path(__file__).resolve().parents[1])
    rom = Path('/root/sheng-pixelos/android')
    parent = json.loads(args.installed_pair.read_text())
    policy = json.loads(args.policy_qualification.read_text())
    assert parent['passed'] and parent['paired_module_payloads_equal']
    assert policy['passed'] and policy['neverallows_checked']
    assert policy['permissive_domains_unchanged'] and policy['exact_context'] == CONTEXT
    retained = Path(policy['retained_work'])
    for name, expected in policy['retained_outputs'].items():
        assert sha(retained / name) == expected, name
    compiled = retained / 'candidate.policy'
    assert sha(compiled) == policy['candidate_policy_sha256']
    images = {name: Path(row['path']) for name, row in parent['images'].items()}
    assert set(images) == {'recovery', 'vendor_boot'}
    for name, path in images.items():
        assert sha(path) == parent['images'][name]['sha256']
    output = args.output.resolve()
    assert not output.exists()
    (output / 'images').mkdir(parents=True)
    (output / 'logs').mkdir()
    scratch = Path(tempfile.mkdtemp(prefix='sheng-usb-policy-package-'))

    def run(argv, label, data=None):
        result = subprocess.run(list(map(str, argv)), input=data, capture_output=True, timeout=120)
        (output / 'logs' / (label + '.stdout')).write_bytes(result.stdout)
        (output / 'logs' / (label + '.stderr')).write_bytes(result.stderr)
        assert result.returncode == 0, result.stderr.decode(errors='replace')[-4000:]
        return result.stdout

    avb_path = rom / 'external/avb/avbtool.py'
    spec = importlib.util.spec_from_file_location('avbtool', avb_path)
    avb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(avb)

    def avb_info(image):
        handler = avb.ImageHandler(str(image), read_only=True)
        try:
            return avb.Avb()._parse_image(handler)
        finally:
            handler._image.close()

    def unpack(image, label):
        directory = scratch / label
        raw = run(['python3', rom / 'system/tools/mkbootimg/unpack_bootimg.py',
                   '--boot_img', image, '--out', directory, '--format', 'mkbootimg', '-0'], label)
        assert raw.endswith(b'\0')
        return [s.decode() for s in raw[:-1].split(b'\0')], directory

    run(['python3', avb_path, 'verify_image', '--image', images['recovery']], 'parent-footer')
    argv, before = unpack(images['recovery'], 'before')
    index = argv.index('--ramdisk') + 1
    plain = run(['lz4', '-dc', argv[index]], 'decompress')
    entries, _ = parse_cpio(plain)
    inventory = {entry['name']: entry for entry in entries}
    assert digest(inventory['sepolicy']['payload']) == policy['baseline_reproduced_sha256']
    for partition in ('plat', 'system_ext', 'product', 'vendor', 'odm'):
        name = partition + '_property_contexts'
        expected = inventory[name]['payload']
        assert PROPERTY.encode() not in expected
        if partition == 'vendor':
            expected = expected + b'\n' + CONTEXT.encode() + b'\n'
        assert (retained / name).read_bytes() == expected, name
    replacements = {'sepolicy': compiled.read_bytes(),
                    'vendor_property_contexts': (retained / 'vendor_property_contexts').read_bytes()}
    packed = replace_records(plain, replacements, parse_cpio)
    compressed = scratch / 'candidate.lz4'
    compressed.write_bytes(run(['lz4', '-l', '-9', '-c'], 'compress', packed))
    changed = argv.copy()
    changed[index] = str(compressed)
    image = output / 'images/recovery.img'
    run(['python3', rom / 'system/tools/mkbootimg/mkbootimg.py', *changed, '--output', image], 'pack')
    _, header, descriptors, _ = avb_info(images['recovery'])
    assert header.algorithm_type == 0
    hashes = [d for d in descriptors if isinstance(d, avb.AvbHashDescriptor)]
    assert len(hashes) == 1 and hashes[0].partition_name == 'recovery'
    h = hashes[0]
    seal = ['python3', avb_path, 'add_hash_footer', '--image', image,
            '--partition_size', images['recovery'].stat().st_size, '--partition_name', 'recovery',
            '--algorithm', 'NONE', '--salt', h.salt.hex(), '--hash_algorithm', h.hash_algorithm,
            '--flags', header.flags, '--rollback_index', header.rollback_index,
            '--rollback_index_location', header.rollback_index_location]
    for d in descriptors:
        if isinstance(d, avb.AvbPropertyDescriptor):
            seal += ['--prop', d.key + ':' + d.value.decode()]
        else:
            assert isinstance(d, avb.AvbHashDescriptor)
    run(seal, 'seal')
    run(['python3', avb_path, 'verify_image', '--image', image], 'candidate-footer')
    new_argv, after = unpack(image, 'after')
    normalize = lambda words, folder: ['PART/' + Path(s).name if s.startswith(str(folder) + '/') else s for s in words]
    assert normalize(argv, before) == normalize(new_argv, after)
    assert run(['lz4', '-dc', new_argv[index]], 'readback') == packed
    final_entries, _ = parse_cpio(packed)
    final = {entry['name']: entry for entry in final_entries}
    assert set(final) == set(inventory)
    assert {n for n in final if final[n]['raw'] != inventory[n]['raw']} == set(replacements)
    modules = {n: digest(e['payload']) for n, e in final.items() if n.endswith('.ko')}
    assert len(modules) == 343
    _, new_header, new_descriptors, _ = avb_info(image)
    assert vars(header) == vars(new_header)
    assert [d.encode() for d in descriptors if not isinstance(d, avb.AvbHashDescriptor)] == [
        d.encode() for d in new_descriptors if not isinstance(d, avb.AvbHashDescriptor)]
    for component in ('kernel', 'dtb', 'bootconfig'):
        if (before / component).exists():
            assert (before / component).read_bytes() == (after / component).read_bytes()
    receipt = dict(parent)
    receipt.update(parents={name: dict(path=str(path), sha256=sha(path)) for name, path in images.items()},
                   policy_only_delta=sorted(replacements), installed_parent_qualification_sha256=sha(args.installed_pair),
                   policy_qualification_sha256=sha(args.policy_qualification),
                   baseline_policy_sha256=policy['baseline_reproduced_sha256'],
                   candidate_policy_sha256=sha(compiled), exact_context=CONTEXT,
                   runtime_verified=False, flashed=False, cold_runtime_verified=False,
                   all_enforcing_recovery_verified=False, offline_only=True,
                   linux_scratch=str(scratch), module_payloads_unchanged=True)
    receipt['images'] = {'vendor_boot': dict(parent['images']['vendor_boot']),
                         'recovery': dict(path=str(image), sha256=sha(image), bytes=image.stat().st_size,
                                          replaced_paths=sorted(replacements), added_paths=[])}
    (output / 'qualification.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
