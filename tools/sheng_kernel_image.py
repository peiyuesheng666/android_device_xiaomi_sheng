#!/usr/bin/env python3
"""Finalize/check the post-module Image against vmlinux and split-BTF base.

Do not use timestamps, uname or a receipt alone to establish equivalence. Run
the pinned Kbuild objcopy recipe again and compare the actual image bytes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import tempfile


RECIPE = ['llvm-objcopy', '-O', 'binary', '-R', '.note', '-R',
          '.note.gnu.build-id', '-R', '.comment', '-S', 'vmlinux',
          'arch/arm64/boot/Image']


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sections(data):
    if data[:6] != b'\x7fELF\x02\x01' or len(data) < 64:
        raise ValueError('Expected little-endian ELF64 vmlinux')
    offset = struct.unpack_from('<Q', data, 40)[0]
    size, count, names_index = struct.unpack_from('<HHH', data, 58)
    if size != 64 or not 0 < names_index < count or offset + size * count > len(data):
        raise ValueError('Invalid section table')
    table = [struct.unpack_from('<IIQQQQIIQQ', data, offset + i * size) for i in range(count)]
    names_row = table[names_index]
    names = data[names_row[4]:names_row[4]+names_row[5]]
    result = {}
    for row in table:
        if row[0] >= len(names):
            raise ValueError('Invalid section name')
        name = names[row[0]:].split(b'\0', 1)[0].decode()
        if row[1] == 8:  # SHT_NOBITS has no bytes in the file.
            continue
        if row[4] + row[5] > len(data) or name in result:
            raise ValueError('Invalid or duplicate section')
        result[name] = (row[1], data[row[4]:row[4]+row[5]])
    return result


def build_id(elf_sections):
    ids = []
    for kind, data in elf_sections.values():
        if kind != 7:  # SHT_NOTE
            continue
        cursor = 0
        while cursor + 12 <= len(data):
            ns, ds, note_kind = struct.unpack_from('<III', data, cursor)
            cursor += 12
            name = data[cursor:cursor+ns].rstrip(b'\0')
            cursor += (ns+3) & ~3
            value = data[cursor:cursor+ds]
            cursor += (ds+3) & ~3
            if cursor > len(data):
                raise ValueError('Truncated ELF note')
            if name == b'GNU' and note_kind == 3:
                ids.append(value.hex())
    if len(ids) != 1 or not ids[0]:
        raise ValueError('Expected one GNU kernel build ID')
    return ids[0]


def qualify(core, objcopy, *, finalize=False, evidence=None):
    core, objcopy = core.resolve(strict=True), objcopy.resolve(strict=True)
    command = core/'arch/arm64/boot/.Image.cmd'
    saved = command.read_text().strip().split(':=', 1)
    if len(saved) != 2 or saved[0].strip() != 'savedcmd_arch/arm64/boot/Image' or shlex.split(saved[1]) != RECIPE:
        raise ValueError('Unrecognized Kbuild Image recipe; do not guess')
    tracked = ['vmlinux', '.config', 'kernel.config', 'Module.symvers',
               'kernel-module-base.btf', 'arch/arm64/boot/.Image.cmd']
    hashes = {name: sha(core/name) for name in tracked}
    elf_sections = sections((core/'vmlinux').read_bytes())
    if elf_sections['.BTF'][1] != (core/'kernel-module-base.btf').read_bytes():
        raise ValueError('Module BTF base is not the final vmlinux .BTF')
    ready = json.loads((core/'.kernel-ready.json').read_text())
    if hashes['.config'] != hashes['kernel.config'] or ready['kernel_config_sha256'] != hashes['.config']:
        raise ValueError('Final configuration differs from the core build receipt')
    receipt = dict(schema=1, final_vmlinux_build_id=build_id(elf_sections),
                   inputs_sha256=hashes, objcopy_sha256=sha(objcopy), recipe=RECIPE)
    with tempfile.TemporaryDirectory(prefix='sheng-image-') as directory:
        generated = Path(directory)/'Image'
        subprocess.run([str(objcopy), *RECIPE[1:-2], str(core/'vmlinux'), str(generated)], check=True, capture_output=True)
        receipt['kernel_image_sha256'] = sha(generated)
        # Recheck inputs to reject an active/relinking build racing this gate.
        if hashes != {name: sha(core/name) for name in tracked}:
            raise ValueError('Kernel inputs changed during finalization')
        if finalize:
            if evidence is None:
                raise ValueError('Fresh evidence directory required before replacing Image')
            evidence.mkdir(parents=True, exist_ok=False)
            for name in ['arch/arm64/boot/Image', 'kernel-Image', '.kernel-ready.json', 'kernel-image-final.json']:
                path = core/name
                if path.exists():
                    shutil.copy2(path, evidence/path.name)
            for name in ('arch/arm64/boot/Image', 'kernel-Image'):
                path = core/name
                temporary = path.with_name(path.name+'.sheng-final.tmp')
                with temporary.open('xb') as stream:
                    with generated.open('rb') as source:
                        shutil.copyfileobj(source, stream)
                temporary.replace(path)
            ready['kernel_image_sha256'] = receipt['kernel_image_sha256']
            ready['final_vmlinux_sha256'] = hashes['vmlinux']
            ready['final_vmlinux_build_id'] = receipt['final_vmlinux_build_id']
            for name, value in [('kernel-image-final.json', receipt), ('.kernel-ready.json', ready)]:
                path = core/name
                temporary = path.with_name(path.name+'.sheng-final.tmp')
                with temporary.open('x') as stream:
                    json.dump(value, stream, indent=2); stream.write('\n')
                temporary.replace(path)
            (evidence/'finalization.json').write_text(json.dumps(receipt, indent=2)+'\n')
        for name in ('arch/arm64/boot/Image', 'kernel-Image'):
            if sha(core/name) != receipt['kernel_image_sha256']:
                raise ValueError('Stale Image: '+name+' does not derive from final vmlinux')
        if json.loads((core/'kernel-image-final.json').read_text()) != receipt:
            raise ValueError('Final Image receipt does not match independently derived bytes')
        if json.loads((core/'.kernel-ready.json').read_text())['kernel_image_sha256'] != receipt['kernel_image_sha256']:
            raise ValueError('Core readiness receipt has stale Image hash')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-out', type=Path, required=True)
    parser.add_argument('--objcopy', type=Path, required=True)
    parser.add_argument('--finalize', action='store_true')
    parser.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    print(json.dumps(qualify(args.kernel_out, args.objcopy, finalize=args.finalize, evidence=args.evidence), indent=2))


if __name__ == '__main__':
    main()
