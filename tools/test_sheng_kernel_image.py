"""Real LLVM fixture tests for the final-vmlinux/Image packaging gate."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from sheng_kernel_image import RECIPE, qualify, sha

TOOLCHAIN = Path(os.environ.get('SHENG_TEST_LLVM', '/root/sheng-pixelos/diagnostics/kernel618-android-deps/prebuilts/clang/host/linux-x86/clang-r584948c/bin'))


class FinalImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.core = self.root/'core'; self.core.mkdir()
        (self.core/'arch/arm64/boot').mkdir(parents=True)
        asm = self.root/'fixture.s'
        asm.write_text('''
.text
.global _start
_start: ret
.section .notes,"a",%note
.balign 4
.long 4, 4, 3
.asciz "GNU"
.long 0x12345678
.section .BTF,"a"
.byte 0x9f,0xeb,1,0
''')
        subprocess.run([str(TOOLCHAIN/'clang'), '--target=aarch64-linux-gnu', '-c', str(asm), '-o', str(self.core/'vmlinux')], check=True, capture_output=True)
        (self.core/'arch/arm64/boot/.Image.cmd').write_text('savedcmd_arch/arm64/boot/Image := '+' '.join(RECIPE)+'\n')
        for name in ('.config', 'kernel.config'):
            (self.core/name).write_text('CONFIG_MODVERSIONS=y\n')
        (self.core/'Module.symvers').write_text('test symbols\n')
        (self.core/'kernel-module-base.btf').write_bytes(bytes.fromhex('9feb0100'))
        (self.core/'arch/arm64/boot/Image').write_bytes(b'old Image')
        (self.core/'kernel-Image').write_bytes(b'old Image')
        (self.core/'.kernel-ready.json').write_text(json.dumps(dict(kernel_config_sha256=sha(self.core/'.config'), kernel_image_sha256=sha(self.core/'kernel-Image'))))
        self.objcopy = TOOLCHAIN/'llvm-objcopy'

    def finalize(self):
        return qualify(self.core, self.objcopy, finalize=True, evidence=self.root/'evidence')

    def test_finalization_and_independent_recheck(self):
        row = self.finalize()
        self.assertEqual(row['final_vmlinux_build_id'], '78563412')
        self.assertEqual(row, qualify(self.core, self.objcopy))
        self.assertEqual((self.root/'evidence/kernel-Image').read_bytes(), b'old Image')

    def test_stale_image_rejected_without_receipt(self):
        with self.assertRaisesRegex(ValueError, 'Stale Image'):
            qualify(self.core, self.objcopy)

    def test_tamper_actual_image(self):
        self.finalize()
        (self.core/'arch/arm64/boot/Image').write_bytes(b'old Image')
        with self.assertRaisesRegex(ValueError, 'Stale Image'):
            qualify(self.core, self.objcopy)

    def test_forged_receipt_does_not_bypass_derivation(self):
        self.finalize()
        for name in ('kernel-Image', 'arch/arm64/boot/Image'):
            (self.core/name).write_bytes(b'forged image')
        receipt = json.loads((self.core/'kernel-image-final.json').read_text())
        receipt['kernel_image_sha256'] = sha(self.core/'kernel-Image')
        (self.core/'kernel-image-final.json').write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, 'Stale Image'):
            qualify(self.core, self.objcopy)

    def test_btf_mismatch_fails_before_replacement(self):
        (self.core/'kernel-module-base.btf').write_bytes(b'wrong base')
        with self.assertRaisesRegex(ValueError, 'Module BTF base'):
            self.finalize()
        self.assertEqual((self.core/'kernel-Image').read_bytes(), b'old Image')
        self.assertFalse((self.root/'evidence').exists())

    def test_config_mismatch(self):
        (self.core/'.config').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'configuration'):
            self.finalize()

    def test_unknown_recipe_rejected(self):
        with (self.core/'arch/arm64/boot/.Image.cmd').open('a') as stream:
            stream.write('; echo injected')
        with self.assertRaisesRegex(ValueError, 'Unrecognized'):
            self.finalize()

    def test_evidence_cannot_be_overwritten(self):
        self.finalize()
        with self.assertRaises(FileExistsError):
            self.finalize()

    def test_receipt_tampering(self):
        self.finalize()
        (self.core/'kernel-image-final.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'receipt'):
            qualify(self.core, self.objcopy)


if __name__ == '__main__':
    unittest.main()
