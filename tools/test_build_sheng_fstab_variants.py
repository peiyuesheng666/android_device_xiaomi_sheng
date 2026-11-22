#!/usr/bin/env python3
"""Test the bounded Ninja extraction parser; never execute graph commands."""
from pathlib import Path
import tempfile
import unittest

from build_sheng_fstab_variants import blocks, build_edge, statements


class NinjaExtractionTest(unittest.TestCase):
    def parse(self, source, parser=statements):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'input.ninja'
            path.write_text(source)
            return list(parser(path))

    def test_multiline_prebuilt_edge(self):
        result = self.parse('build $\n    target: $\n    cp source | Rm-deps $\n    Cp-deps\n')
        self.assertEqual(result, ['build target: cp source | Rm-deps Cp-deps'])
        self.assertEqual(build_edge(result), ('target', 'cp', ['source', '|', 'Rm-deps', 'Cp-deps']))

    def test_preserve_build_bindings(self):
        result = self.parse('rule cp\n    command = cp ${in} ${out}\n\nbuild dst: cp src\n    tags = fstab\n', blocks)
        self.assertEqual(len(result), 2)
        self.assertIn('    tags = fstab', result[1])

    def test_unfinished_continuation_rejected(self):
        with self.assertRaises(AssertionError):
            self.parse('build $\n')

    def test_multiple_outputs_rejected(self):
        with self.assertRaises(AssertionError):
            build_edge(['build a b: cp source'])

    def test_escaped_dollar_not_continuation(self):
        self.assertEqual(self.parse('value = literal$$\nnext = ok\n'),
                         ['value = literal$$', 'next = ok'])

    def test_large_continuation_keeps_tokens(self):
        result = self.parse('build out: phony $\n' + ' x $\n'*10000 + ' last\n')
        self.assertEqual(result[0].split().count('x'), 10000)
        self.assertTrue(result[0].endswith('last'))


if __name__ == '__main__':
    unittest.main()
