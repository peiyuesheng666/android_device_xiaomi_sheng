#!/usr/bin/env python3
"""Host-only tests; no WSL startup, images, adb, filesystem writes or flash."""
from pathlib import Path
import importlib.util
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import storage_guard as guard


class StoragePreflightTests(unittest.TestCase):
    def test_enough_space(self):
        with patch.object(guard.shutil, 'disk_usage', return_value=SimpleNamespace(free=3 * guard.GIB)):
            rows = guard.require_build_space(HERE, host_volume=HERE)
        self.assertEqual(len(rows), 2)

    def test_ext4_free_does_not_override_full_host(self):
        with patch.object(guard.shutil, 'disk_usage', side_effect=[
                SimpleNamespace(free=300 * guard.GIB), SimpleNamespace(free=0)]):
            with self.assertRaisesRegex(RuntimeError, 'Windows host volume'):
                guard.require_build_space(HERE, host_volume=HERE)

    def test_insufficient_output_fails_before_host(self):
        with patch.object(guard.shutil, 'disk_usage', return_value=SimpleNamespace(free=100)) as usage:
            with self.assertRaisesRegex(RuntimeError, 'output filesystem'):
                guard.require_build_space(HERE, host_volume=HERE)
            self.assertEqual(usage.call_count, 1)

    def test_storage_query_failure_is_not_ignored(self):
        with patch.object(guard.shutil, 'disk_usage', side_effect=OSError('I/O error')):
            with self.assertRaises(OSError):
                guard.require_build_space(HERE, host_volume=HERE)

    def test_nonexistent_output_checks_existing_ancestor(self):
        path = HERE / 'uncreated-storage-preflight-output' / 'nested'
        self.assertFalse(path.exists())
        self.assertEqual(guard.existing_ancestor(path), HERE)
        self.assertFalse(path.exists())

    def test_invalid_minimum_is_rejected(self):
        with self.assertRaises(ValueError):
            guard.require_build_space(HERE, host_volume=HERE, minimum_output=0)

    def test_exact_headroom_boundary(self):
        with patch.object(guard.shutil, 'disk_usage', side_effect=[
                SimpleNamespace(free=2 * guard.GIB), SimpleNamespace(free=guard.GIB)]):
            self.assertEqual(len(guard.require_build_space(HERE, host_volume=HERE)), 2)


class CapturePreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = HERE.parents[4] / 'scripts/capture_sheng_magisk_remounter.py'
        spec = importlib.util.spec_from_file_location('sheng_capture_preflight_test', path)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_low_space_does_not_contact_device_or_create_output(self):
        module = self.module
        path = HERE / 'uncreated-storage-preflight-output'
        with patch.object(module, 'require_build_space', side_effect=RuntimeError('disk full')), \
             patch.object(module.subprocess, 'run') as run, \
             patch.object(Path, 'mkdir') as mkdir, \
             patch.object(sys, 'argv', ['capture', str(path)]):
            with self.assertRaisesRegex(RuntimeError, 'disk full'):
                module.main()
            run.assert_not_called()
            mkdir.assert_not_called()

    def test_missing_image_does_not_contact_device_or_create_output(self):
        module = self.module
        with patch.object(module, 'require_build_space'), \
             patch.object(module, 'image_sha256', side_effect=FileNotFoundError('missing image')), \
             patch.object(module.subprocess, 'run') as run, \
             patch.object(Path, 'mkdir') as mkdir, \
             patch.object(sys, 'argv', ['capture', str(HERE / 'uncreated-output')]):
            with self.assertRaises(FileNotFoundError):
                module.main()
            run.assert_not_called()
            mkdir.assert_not_called()

    def test_wrong_image_hash_does_not_contact_device(self):
        module = self.module
        with patch.object(module, 'require_build_space'), \
             patch.object(module, 'image_sha256', return_value='0' * 64), \
             patch.object(module.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'hash mismatch'):
                module.preflight_inputs(HERE / 'uncreated-output')
            run.assert_not_called()

    def test_partial_custom_pair_does_not_contact_device(self):
        module = self.module
        with patch.object(module.subprocess, 'run') as run, \
             patch.object(Path, 'mkdir') as mkdir, \
             patch.object(sys, 'argv', ['capture', str(HERE / 'uncreated-output'),
                                      '--capture-image', 'diagnostic.img']):
            with self.assertRaises(SystemExit):
                module.main()
            run.assert_not_called()
            mkdir.assert_not_called()

    def test_custom_pair_checks_both_pinned_files(self):
        module = self.module
        images = {'boot.img': Path('preserve.img'), 'boot.capture45.img': Path('diagnostic.img')}
        expected = {'boot.img': '1' * 64, 'boot.capture45.img': '2' * 64}
        with patch.object(module, 'require_build_space'), \
             patch.object(module, 'image_sha256', side_effect=['1' * 64, '2' * 64]) as digest, \
             patch.object(module.subprocess, 'run') as run:
            module.preflight_inputs(HERE / 'uncreated-output', images, expected)
            self.assertEqual([call.args[0] for call in digest.call_args_list], list(images.values()))
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
