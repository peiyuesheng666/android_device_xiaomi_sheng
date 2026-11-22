import unittest

from read_physical_backing import extents_for, read_command


class ExtentTests(unittest.TestCase):
    def test_binary_stream_has_remote_stderr_redirect(self):
        command = read_command({'offset': 1048576, 'bytes': 4096})
        self.assertTrue(command.endswith('skip=1048576 count=4096 2>/dev/null'))
        self.assertNotIn('of=', command)

    def layout(self, rows='    0 .. 7 linear super 2048', attributes='readonly,updated'):
        return ('  Name: system_ext_b\n  Group: qti_dynamic_partitions_b\n'
                f'  Attributes: {attributes}\n  Extents:\n{rows}\n------------------------\n')

    def parse(self, layout, expected=4096):
        return extents_for(layout, 'system_ext_b', 16 * 1024**2, expected)

    def test_valid_and_preserve_updated(self):
        rows, attr = self.parse(self.layout())
        self.assertEqual(rows, [{'offset': 1048576, 'bytes': 4096}])
        self.assertEqual(attr, 'readonly,updated')

    def test_fragmented_physical_order(self):
        rows, _ = self.parse(self.layout('    0 .. 3 linear super 4096\n    4 .. 7 linear super 2048'))
        self.assertEqual([r['offset'] for r in rows], [2097152, 1048576])

    def test_reject_bad_rows(self):
        for rows in ('    0 .. 7 zero', '    0 .. 7 linear other 2048',
                     '    0 .. 7 linear super 2048 garbage', '',
                     '    0 .. 7 linear super 2048\nunknown'):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.parse(self.layout(rows))

    def test_reject_gap_overlap_reversed(self):
        for rows in ('    1 .. 8 linear super 2048',
                     '    0 .. 3 linear super 2048\n    5 .. 8 linear super 4096',
                     '    0 .. 3 linear super 2048\n    4 .. 7 linear super 2050',
                     '    0 .. 3 linear super 2048\n    3 .. 6 linear super 4096',
                     '    0 .. 7 linear super 32768', '    0 .. 7 linear super 0',
                     '    0 .. 7 linear super 2047', '    0 .. 7 linear super 2048\n    8 .. 6 linear super 4096'):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.parse(self.layout(rows))

    def test_reject_missing_duplicate_wrong_size(self):
        for text in ('', self.layout() * 2, self.layout().replace('  Attributes: readonly,updated\n', '')):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.parse(text)
        with self.assertRaises(ValueError):
            self.parse(self.layout(), 8192)

    def test_reject_name_injection(self):
        for name in ('system_ext_b; reboot', 'system_ext_a', 'system_ext_b-cow'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                extents_for(self.layout(), name, 16 * 1024**2, 4096)


if __name__ == '__main__':
    unittest.main()
