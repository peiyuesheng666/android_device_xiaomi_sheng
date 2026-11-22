import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from prepare_sheng_wlan_response import ANCHOR, REPLACEMENT, patched


class WlanResponseTests(unittest.TestCase):
    def test_scoped_idempotent_edit(self):
        original = 'before\n' + ANCHOR + 'after\n'
        result = patched(original)
        self.assertEqual(result, 'before\n' + REPLACEMENT + 'after\n')
        self.assertEqual(patched(result), result)

    def test_unknown_partial_and_duplicate_rejected(self):
        for text in ('unknown', ANCHOR * 2, ANCHOR + 'sheng_wlan_inc_rsp'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                patched(text)

    @unittest.skipUnless(shutil.which('make') and shutil.which('clang'), 'Native compiler fixture')
    def test_long_ordered_flags_compile_and_invalidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, value in [('first', 17), ('second', 29)]:
                (root / name).mkdir()
                (root / name / 'choice.h').write_text('#define CHOICE ' + str(value) + '\n')
            (root / 'probe.c').write_text('#include "choice.h"\nint choice = CHOICE;\n')
            # Exceed Linux's per-string exec limit without passing those bytes
            # as a shell argument. Repeated flags and search order are retained.
            flags = '-I' + str(root / 'first') + ' -I' + str(root / 'second')
            flags += (' -I' + str(root / ('unused_' + 'x' * 80))) * 1600
            self.assertGreater(len(flags), 131072)
            makefile = root / 'Makefile'

            def run(includes):
                makefile.write_text('obj := ' + str(root) + '\nINCS := ' + includes + '\n'
                                    + REPLACEMENT + '\n.PHONY: all\nall:\n'
                                    '\t@printf "%s\\n" "$(ccflags-y)" > flags.txt\n'
                                    '\tclang $(ccflags-y) -E -P probe.c -o probe.i\n'
                                    '\tclang $(ccflags-y) -c probe.c -o probe.o\n')
                proc = subprocess.run(['make', '-s'], cwd=root, capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                response = (root / 'flags.txt').read_text().strip()[1:]
                self.assertEqual(Path(response).read_text().strip(), includes)
                return response

            first = run(flags)
            self.assertIn('int choice = 17;', (root / 'probe.i').read_text())
            self.assertEqual(run(flags), first)
            reordered = flags.replace('-I' + str(root / 'first') + ' -I' + str(root / 'second'),
                                      '-I' + str(root / 'second') + ' -I' + str(root / 'first'), 1)
            second = run(reordered)
            self.assertNotEqual(second, first)
            self.assertIn('int choice = 29;', (root / 'probe.i').read_text())
            digest = hashlib.sha256((reordered + '\n').encode()).hexdigest()
            self.assertIn(digest, second)


if __name__ == '__main__':
    unittest.main()
