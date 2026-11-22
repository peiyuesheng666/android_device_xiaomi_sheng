import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import qualify_remounter_soong_graph as qualifier
from qualify_remounter_soong_graph import relocate_testcase_outputs, discover_blueprints


class AnalysisStorageTests(unittest.TestCase):
    def test_reserves_growth_in_addition_to_unchanged_stop_floor(self):
        with patch.object(qualifier, 'require_build_space', return_value=[]) as check:
            qualifier.require_analysis_space(Path('native-out'), Path('report'))
        self.assertEqual(qualifier.HOST_FLOOR_BYTES, 6442450944)
        self.assertEqual(check.call_args_list[0].kwargs['minimum_host'], 14 * 1024**3)
        self.assertEqual(check.call_args_list[0].kwargs['minimum_output'], 8 * 1024**3)
        self.assertEqual(check.call_args_list[1].kwargs['minimum_host'], 14 * 1024**3)

    def test_low_space_stops_preflight(self):
        with patch.object(qualifier, 'require_build_space', side_effect=RuntimeError('disk full')) as check:
            with self.assertRaisesRegex(RuntimeError, 'disk full'):
                qualifier.require_analysis_space(Path('native-out'), Path('report'))
        self.assertEqual(check.call_count, 1)


class DiscoveryTests(unittest.TestCase):
    def test_pruning_and_new_owned_module(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('device/owned/new', 'public/core', '.git/ignored',
                         '.repo/ignored', 'out/generated', 'ignored/child'):
                p = root / name
                p.mkdir(parents=True)
                (p / 'Android.bp').touch()
            (root / 'out/.out-dir').touch()
            (root / 'ignored/.find-ignore').touch()
            (root / 'alias').symlink_to(root / 'public', target_is_directory=True)
            self.assertEqual(discover_blueprints(root),
                             ['device/owned/new/Android.bp', 'public/core/Android.bp'])


class RelocationTests(unittest.TestCase):
    def test_only_output_paths_change_original_is_unchanged(self):
        original = dict(Debuggable=True, VendorVars={'PATH': 'old-out/.path'},
                        CompatibilityTestcases={'catbox': {'OutDir': 'old-out/host/testcases'}})
        changed, count = relocate_testcase_outputs(original, 'old-out', 'new-out')
        self.assertEqual(count, 1)
        self.assertEqual(changed['CompatibilityTestcases']['catbox']['OutDir'], 'new-out/host/testcases')
        self.assertEqual(original['CompatibilityTestcases']['catbox']['OutDir'], 'old-out/host/testcases')
        self.assertEqual(changed['VendorVars'], original['VendorVars'])
        self.assertEqual(changed['Debuggable'], original['Debuggable'])

    def test_reject_foreign_or_parent_path(self):
        for path in ('foreign-out/testcases', 'old-out/../outside'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                relocate_testcase_outputs({'CompatibilityTestcases': {'cts': {'OutDir': path}}},
                                          'old-out', 'new-out')


if __name__ == '__main__':
    unittest.main()
