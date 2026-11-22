#!/usr/bin/env python3
"""Create bounded logging boot from the failed trial, changing only cmdline.

Caller must back up the logger's entire 288..290 MiB region before using this.
After automatic bootloader return, restore preserve-rawdump boot before Recovery.
"""
from pathlib import Path
import argparse
import importlib.util
import json
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[4] / 'scripts'))
from build_sheng_fastbootd_cold_trace import sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('parent', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--expected-parent-sha256',
                        default='53a9c8620db57da5bed7c5373147d7a0c9adc5dc7ab4cb467d021ec80b934cd3',
                        help='Explicit pinned hash for a separately qualified diagnostic parent')
    options = parser.parse_args()
    parent, out = options.parent, options.out
    expected = options.expected_parent_sha256
    assert re.fullmatch('[0-9a-f]{64}', expected), 'Invalid expected parent SHA-256'
    assert sha(parent) == expected
    out.mkdir(exist_ok=False)
    a = Path('/root/sheng-pixelos/android')
    avbpath = a / 'external/avb/avbtool.py'
    spec = importlib.util.spec_from_file_location('avbtool', avbpath)
    avb = importlib.util.module_from_spec(spec); spec.loader.exec_module(avb)

    def run(cmd, label):
        p = subprocess.run(list(map(str, cmd)), capture_output=True, timeout=90)
        (out / (label + '.stdout')).write_bytes(p.stdout)
        (out / (label + '.stderr')).write_bytes(p.stderr)
        assert p.returncode == 0, (label, p.stderr)
        return p.stdout

    before = out / 'before'
    args = run(['python3', a / 'system/tools/mkbootimg/unpack_bootimg.py', '--boot_img', parent,
                '--out', before, '--format', 'mkbootimg', '-0'], 'unpack')
    args = [x.decode() for x in args[:-1].split(b'\0')]
    idx = args.index('--cmdline') + 1
    old = args[idx]
    assert old.split().count('sheng_bootlog.enable=0') == 1
    assert old.split().count('sheng_bootlog.test_timeout=0') == 1
    new = old.replace('sheng_bootlog.enable=0', 'sheng_bootlog.enable=1').replace(
        'sheng_bootlog.test_timeout=0', 'sheng_bootlog.test_timeout=45')
    args[idx] = new
    image = out / 'boot.img'
    run(['python3', a / 'system/tools/mkbootimg/mkbootimg.py', *args, '--output', image], 'pack')
    handler = avb.ImageHandler(str(parent), read_only=True)
    try:
        _, header, desc, _ = avb.Avb()._parse_image(handler)
    finally:
        handler._image.close()
    assert header.algorithm_type == 0
    hashes = [d for d in desc if isinstance(d, avb.AvbHashDescriptor)]
    assert len(hashes) == 1 and hashes[0].partition_name == 'boot'
    h = hashes[0]
    cmd = ['python3', avbpath, 'add_hash_footer', '--image', image, '--partition_size', parent.stat().st_size,
           '--partition_name', 'boot', '--algorithm', 'NONE', '--salt', h.salt.hex(), '--hash_algorithm', h.hash_algorithm,
           '--flags', header.flags, '--rollback_index', header.rollback_index, '--rollback_index_location', header.rollback_index_location]
    for d in desc:
        if isinstance(d, avb.AvbPropertyDescriptor):
            cmd += ['--prop', d.key + ':' + d.value.decode()]
        else:
            assert isinstance(d, avb.AvbHashDescriptor)
    run(cmd, 'footer')
    run(['python3', avbpath, 'verify_image', '--image', image], 'verify')
    after = out / 'after'
    raw = run(['python3', a / 'system/tools/mkbootimg/unpack_bootimg.py', '--boot_img', image,
               '--out', after, '--format', 'mkbootimg', '-0'], 'readback')
    final = [x.decode() for x in raw[:-1].split(b'\0')]
    normalize = lambda argv, folder: ['PART/' + Path(x).name if x.startswith(str(folder) + '/') else x for x in argv]
    assert normalize(args, before) == normalize(final, after)
    for p in before.iterdir():
        assert p.is_file() and p.read_bytes() == (after / p.name).read_bytes()
    q = dict(passed=True, parent_sha256=expected, path=str(image), sha256=sha(image),
             changed=['cmdline.sheng_bootlog.enable', 'cmdline.sheng_bootlog.test_timeout'],
             timeout_seconds=45, kernel_ramdisk_unchanged=True, standalone_avb_verified=True,
             logger_writes_only_bounded_region=True, flashed=False)
    (out / 'qualification.json').write_text(json.dumps(q, indent=2))
    print(json.dumps(q))


if __name__ == '__main__':
    main()
