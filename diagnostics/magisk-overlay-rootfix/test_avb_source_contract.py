"""Guard device source defaults; does not prove a live AVB trust chain."""
from pathlib import Path
import re
import shlex
import unittest

DEVICE = Path(__file__).resolve().parents[2]


def disabling_flags(arguments):
    tokens = shlex.split(arguments)
    for i, token in enumerate(tokens):
        if token == '--flags':
            if i + 1 == len(tokens):
                raise ValueError('Missing flags value')
            if int(tokens[i + 1], 0) & 3:
                return True
        elif token.startswith('--flags=') and int(token.split('=', 1)[1], 0) & 3:
            return True
    return False


class AvbSourceContractTests(unittest.TestCase):
    def test_reject_either_disable_bit(self):
        for arguments in ('--flags 1', '--flags 2', '--flags 3', '--flags=0x3', '--flags 0 --flags 3'):
            with self.subTest(arguments=arguments):
                self.assertTrue(disabling_flags(arguments))

    def test_normal_flags(self):
        for arguments in ('', '--flags 0', '--rollback_index 1 --flags=0x0'):
            with self.subTest(arguments=arguments):
                self.assertFalse(disabling_flags(arguments))

    def test_device_board_defaults_do_not_disable_avb(self):
        text = (DEVICE / 'BoardConfig.mk').read_text()
        self.assertRegex(text, r'(?m)^BOARD_AVB_ENABLE := true$')
        args = ' '.join(re.findall(r'^BOARD_AVB_MAKE_VBMETA_IMAGE_ARGS\s*[+:?]?=\s*(.*)$', text, re.M))
        self.assertFalse(disabling_flags(args))
        self.assertIn('BOARD_AVB_VBMETA_SYSTEM_KEY_PATH := external/avb/test/data/testkey_rsa2048.pem', text)


if __name__ == '__main__':
    unittest.main()
