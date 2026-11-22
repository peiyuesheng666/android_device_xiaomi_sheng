import unittest
from pathlib import Path
import tempfile

from qualify_captured_avb_chain import (footer_positions, replace_descriptors,
                                      mark_unqualified, verification_commands)


class ChainVerificationTests(unittest.TestCase):
    def test_distinct_pinned_keys_and_chain_descriptor(self):
        commands = verification_commands(Path('avbtool.py'), Path('images'),
            Path('root4096.pem'), Path('child2048.pem'), Path('child.avbpubkey'), 1)
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0][commands[0].index('--key') + 1], 'root4096.pem')
        self.assertEqual(commands[1][commands[1].index('--key') + 1], 'child2048.pem')
        self.assertEqual(commands[0][-1], 'vbmeta_system:1:child.avbpubkey')
        for command in commands:
            self.assertNotIn('--follow_chain_partitions', command)
            self.assertNotIn('--accept_zeroed_hashtree', command)
            self.assertIn('verify_image', command)

    def test_warning_exists_before_qualification(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            mark_unqualified(out)
            self.assertIn('Do not flash root vbmeta alone', (out / 'DO_NOT_FLASH.txt').read_text())
            self.assertFalse((out / 'qualification.json').exists())


class FooterTests(unittest.TestCase):
    def test_at_end_and_before_logical_padding(self):
        image = bytearray(8192)
        image[4032:4036] = b'AVBf'
        image[8128:8132] = b'AVBf'
        self.assertEqual(footer_positions(image, 8192), [(4032, 4032), (8128, 8128)])
        self.assertEqual(footer_positions(image[4096:], 8192), [(8128, 4032)])

    def test_ignore_unaligned_or_short_footer(self):
        image = bytearray(4096)
        image[13:17] = b'AVBf'
        image[-4:] = b'AVBf'
        self.assertEqual(footer_positions(image, 4096), [])

    def test_invalid_bounds(self):
        with self.assertRaises(ValueError):
            footer_positions(bytes(4096), 2048)


class ReplacementTests(unittest.TestCase):
    class Hash:
        def __init__(self, name):
            self.partition_name = name

    class Tree:
        def __init__(self, name):
            self.partition_name = name

    def test_preserve_properties_chain_and_order(self):
        prop, chain = object(), object()
        boot, vendor = self.Hash('boot'), self.Tree('vendor')
        new_boot = self.Hash('boot')
        old = [chain, prop, boot, vendor]
        self.assertEqual(replace_descriptors(old, {'boot': new_boot}, (self.Hash, self.Tree)),
                         [chain, prop, new_boot, vendor])
        self.assertEqual(old, [chain, prop, boot, vendor])

    def test_reject_missing_or_duplicate(self):
        boot, new_boot = self.Hash('boot'), self.Hash('boot')
        for old, replacements in (([boot, boot], {'boot': new_boot}),
                                  ([boot], {'vendor': self.Tree('vendor')})):
            with self.subTest(old=old), self.assertRaises(ValueError):
                replace_descriptors(old, replacements, (self.Hash, self.Tree))


if __name__ == '__main__':
    unittest.main()
