import json
import unittest

from integrate_kernel_mount_fix import (RELATIVE_SOURCE, encode, extend_contract,
                                        sha, updated_manifest)


class ManifestTests(unittest.TestCase):
    def test_only_namespace_entry_changes(self):
        before, after = b'old source\n', b'new source\n'
        old = {RELATIVE_SOURCE: dict(sha256=sha(before), bytes=len(before)),
               'k618/ws/common/other.c': dict(sha256='pinned', bytes=12),
               'k618/link': dict(symlink='target')}
        updated = json.loads(updated_manifest(encode(old), before, after))
        self.assertEqual(updated[RELATIVE_SOURCE], dict(sha256=sha(after), bytes=len(after)))
        self.assertEqual(updated['k618/link'], old['k618/link'])
        self.assertEqual(updated['k618/ws/common/other.c'], old['k618/ws/common/other.c'])

    def test_manifest_mismatch_rejected(self):
        old = {RELATIVE_SOURCE: dict(sha256='wrong', bytes=2)}
        with self.assertRaises(ValueError):
            updated_manifest(encode(old), b'a', b'b')

    def test_unknown_contract_rejected(self):
        with self.assertRaises(ValueError):
            extend_contract(b'unknown checker', '0' * 64)


if __name__ == '__main__':
    unittest.main()
