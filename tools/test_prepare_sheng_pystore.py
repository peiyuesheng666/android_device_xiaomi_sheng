#!/usr/bin/env python3
"""Source-integration safety tests, not kernel or device acceptance."""
import contextlib
import io
import json
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import prepare_sheng_pystore as tool


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = b'known prior logger\n'
        files = {
            'sources/' + tool.LOGGER: self.old,
            'sources/native-layout.h': b'native\n',
            'provenance/native-layout-restoration.json': tool.encode(
                {'files': {'native-layout.h': {'after': tool.digest(b'native\n')}}}),
            'SOURCE-SHA256.json': tool.encode({tool.LOGGER:
                {'sha256': tool.digest(self.old), 'bytes': len(self.old)}}),
            'SOURCE.json': tool.encode({'variant': 'native'}),
            'sheng_defconfig': b'CONFIG_LOG_BUF_SHIFT=17\n# CONFIG_SHENG_BOOTLOG is not set\n',
            'sources/k618/ws/common/arch/arm64/configs/sheng_defconfig': b'CONFIG_LOG_BUF_SHIFT=17\n',
        }
        contract = '''import hashlib,json,os
from pathlib import Path
project=Path(os.environ['PROJECT_ROOT'])
root=Path(os.environ['BUILD_ROOT'])
def verify():
    expected=EXPECTED
    for name,item in expected.items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==item['after']
verify()
'''.replace('EXPECTED', repr({tool.LOGGER: {'after': tool.digest(self.old)}}))
        files['scripts/android_lts_contract.py'] = contract.encode()
        for name, data in files.items():
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        (self.root / 'patches').mkdir()

    def run_tool(self, apply=False):
        argv = ['prepare', '--project', str(self.root)] + (['--apply'] if apply else [])
        with patch('sys.argv', argv), patch.object(tool, 'KNOWN_LOGGER', tool.digest(self.old)), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            tool.main()
        return json.loads(output.getvalue())

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def test_config_preserves_unrelated_and_is_idempotent(self):
        result = tool.config(b'CONFIG_OTHER=y\nCONFIG_SHENG_BOOTLOG=n\nCONFIG_LOG_BUF_SHIFT=17\n')
        self.assertIn(b'CONFIG_OTHER=y\n', result)
        self.assertEqual(result.count(b'CONFIG_SHENG_BOOTLOG='), 1)
        self.assertIn(b'CONFIG_LOG_BUF_SHIFT=22\n', result)
        self.assertEqual(tool.config(result), result)

    def test_dry_run_does_not_change_inputs(self):
        before = self.snapshot()
        self.assertTrue(self.run_tool()['changed'])
        self.assertEqual(before, self.snapshot())

    def test_apply_then_no_delta(self):
        self.assertTrue(self.run_tool(apply=True)['applied'])
        self.assertEqual(self.run_tool()['changed'], [])
        self.assertFalse(self.run_tool()['runtime_verified'])

    def test_contract_failure_rolls_back_all_files(self):
        p = self.root / 'scripts/android_lts_contract.py'
        p.write_text(p.read_text() + '\nraise RuntimeError("intentional rejection")\n')
        before = self.snapshot()
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_tool(apply=True)
        self.assertEqual(before, self.snapshot())

    def test_unknown_source_rejected_without_edits(self):
        p = self.root / 'sources' / tool.LOGGER
        p.write_bytes(b'unrecorded modification')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.run_tool(apply=True)
        self.assertEqual(before, self.snapshot())


if __name__ == '__main__':
    unittest.main()
