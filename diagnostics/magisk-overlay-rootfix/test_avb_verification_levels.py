"""Opt-in real avbtool regression: SHENG_AVB_ROM=/absolute/ROM python -m unittest.

Synthetic hash-protected payloads only; no tablet or product output access.
Proves the split-key verifier rejects wrong keys/chain descriptors and bad data.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from qualify_captured_avb_chain import verification_commands


@unittest.skipUnless(os.environ.get('SHENG_AVB_ROM'), 'Requires retained ROM avbtool and test keys')
class RealVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sheng-avb-level-test-')
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        rom = Path(os.environ['SHENG_AVB_ROM']).resolve(strict=True)
        self.avb = rom / 'external/avb/avbtool.py'
        self.root_key = rom / 'external/avb/test/data/testkey_rsa4096.pem'
        self.child_key = rom / 'external/avb/test/data/testkey_rsa2048.pem'
        self.chain_key = self.work / 'child.avbpubkey'
        self.root_public = self.work / 'root.avbpubkey'
        for key, output in ((self.child_key, self.chain_key), (self.root_key, self.root_public)):
            self.run_avb('extract_public_key', '--key', key, '--output', output)
        self.payload = self.work / 'probe.img'
        self.payload.write_bytes(b'known protected data\n' * 256)
        self.run_avb('add_hash_footer', '--image', self.payload, '--partition_name', 'probe',
                     '--partition_size', '131072', '--algorithm', 'SHA256_RSA2048',
                     '--key', self.child_key)
        self.run_avb('make_vbmeta_image', '--output', self.work / 'vbmeta_system.img',
                     '--include_descriptors_from_image', self.payload,
                     '--algorithm', 'SHA256_RSA2048', '--key', self.child_key)
        self.run_avb('make_vbmeta_image', '--output', self.work / 'vbmeta.img',
                     '--chain_partition', f'vbmeta_system:1:{self.chain_key}',
                     '--algorithm', 'SHA256_RSA4096', '--key', self.root_key)
        self.commands = verification_commands(self.avb, self.work, self.root_key,
                                              self.child_key, self.chain_key, 1)

    def run_avb(self, *args):
        result = subprocess.run(['python3', str(self.avb), *map(str, args)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        return result

    def verify(self, command, success):
        result = subprocess.run(command, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def test_distinct_keys_pass_both_levels(self):
        for command in self.commands:
            self.verify(command, True)

    def test_wrong_root_key_rejected(self):
        command = self.commands[0].copy()
        command[command.index('--key') + 1] = str(self.child_key)
        self.assertIn(b'public key', self.verify(command, False).stderr)

    def test_wrong_chain_key_rejected(self):
        command = self.commands[0].copy()
        command[-1] = f'vbmeta_system:1:{self.root_public}'
        self.verify(command, False)

    def test_wrong_child_key_rejected(self):
        command = self.commands[1].copy()
        command[command.index('--key') + 1] = str(self.root_key)
        self.assertIn(b'public key', self.verify(command, False).stderr)

    def test_corrupted_payload_rejected(self):
        with self.payload.open('r+b') as stream:
            stream.write(b'!')
        self.verify(self.commands[0], True)
        self.verify(self.commands[1], False)


if __name__ == '__main__':
    unittest.main()
