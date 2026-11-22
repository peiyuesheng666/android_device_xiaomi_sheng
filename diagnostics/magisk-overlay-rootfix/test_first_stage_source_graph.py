import unittest

from verify_first_stage_source_graph import (ARCHIVES, FORBIDDEN, validate_link,
                                           validate_copy_chain, validate_analysis,
                                           validate_source_coverage)


class LinkGraphTests(unittest.TestCase):
    def test_requires_terminal_success_not_only_success_flag(self):
        good = dict(graph_generation_passed=True, inputs_unchanged=True,
                    source_variants=True, module_list_rescanned=True,
                    returncode=0, guard_stop=None)
        validate_analysis(good)
        for changes in ({'returncode': None}, {'returncode': 1},
                        {'guard_stop': 'storage guard'}, {'inputs_unchanged': False}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_analysis(dict(good, **changes))

    def test_source_count_cannot_hide_wrong_source(self):
        actual = {'first-stage-init': {'device/xiaomi/sheng/interfaces/compat/first-stage-init/a.cpp'}}
        lock = {'sources': {'original/a.cpp': {
            'destination': 'interfaces/compat/first-stage-init/a.cpp'}}}
        validate_source_coverage(actual, lock)
        lock['sources']['defaults-only'] = {'destination': None}
        validate_source_coverage(actual, lock)
        with self.assertRaises(ValueError):
            validate_source_coverage({'first-stage-init': {
                'device/xiaomi/sheng/interfaces/compat/first-stage-init/wrong.cpp'}}, lock)

    def test_copy_requires_link_to_strip_to_installer_dependency(self):
        link = ['build compiler/unstripped/init: g.cc.ld objects.o']
        strip = ['build compiler/init: g.cc.strip compiler/unstripped/init']
        copy = ['build installer/init: g.android.Cp compiler/init']
        self.assertEqual(validate_copy_chain(link, strip, copy), 'compiler/init')
        self.assertEqual(validate_copy_chain(link, strip, [
            'build installer/init: g.android.CpExecutable compiler/init']), 'compiler/init')
        with self.assertRaises(ValueError):
            validate_copy_chain(link, strip, ['build installer/init: g.android.Symlink compiler/init'])
        with self.assertRaises(ValueError):
            validate_copy_chain(link, ['build compiler/init: g.cc.strip old/unstripped/init'], copy)
        with self.assertRaises(ValueError):
            validate_copy_chain(link, strip, ['build installer/init: g.android.Cp old/init'])
        with self.assertRaises(ValueError):
            validate_copy_chain(link, ['build compiler/init: g.android.Cp compiler/unstripped/init'], copy)

    def good(self):
        paths = ['out/soong/.intermediates/device/xiaomi/sheng/interfaces/compat/' +
                 folder + '/' + name[:-2] + '/android_ramdisk_arm64_static/' + name
                 for name, folder in ARCHIVES.items()]
        return ['build owned/unstripped/init: g.cc.ld object.o', '    libFlags = ' + ' '.join(paths)]

    def test_owned_ramdisk_link(self):
        self.assertEqual(set(validate_link(self.good())), set(ARCHIVES))

    def test_reject_each_original_provider(self):
        for name in FORBIDDEN:
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_link(self.good() + ['    old_provider = out/original/' + name])

    def test_reject_missing_and_wrong_image_variant(self):
        with self.assertRaises(ValueError):
            validate_link(['build init: g.cc.ld object.o'])
        with self.assertRaises(ValueError):
            validate_link([line.replace('android_ramdisk_', 'android_') for line in self.good()])

    def test_reject_renamed_foreign_archive_and_ambiguity(self):
        with self.assertRaises(ValueError):
            validate_link([line.replace('/device/xiaomi/sheng/', '/foreign/') for line in self.good()])
        with self.assertRaises(ValueError):
            validate_link(self.good() + ['    extra = different/libsheng_fs_mgr_first_stage.a'])


if __name__ == '__main__':
    unittest.main()
