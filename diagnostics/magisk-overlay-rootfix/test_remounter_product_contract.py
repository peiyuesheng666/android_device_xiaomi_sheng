"""Source-contract checks, NOT Soong graph or Android runtime acceptance."""
from pathlib import Path
import re
import unittest

DEVICE = Path(__file__).resolve().parents[2]
OWNED = DEVICE / 'interfaces/compat/overlay-remounter'


class ProductContractTests(unittest.TestCase):
    def test_debug_only_product_selection(self):
        product = (OWNED / 'product.mk').read_text()
        self.assertRegex(product, r'(?m)^PRODUCT_PACKAGES_DEBUG \+= overlay_remounter$')
        self.assertNotRegex(product, r'(?m)^PRODUCT_PACKAGES \+=')
        self.assertIn('$(call inherit-product, $(LOCAL_PATH)/interfaces/compat/overlay-remounter/product.mk)',
                      (DEVICE / 'device.mk').read_text())

    def test_override_preserves_original_install_location(self):
        compiler, installer = (OWNED / 'Android.bp').read_text().split('cc_prebuilt_binary {', 1)
        for text in ('name: "sheng_overlay_remounter"', 'stem: "sheng_overlay_remounter"',
                     'static_executable: true'):
            self.assertIn(text, compiler)
        self.assertIn('installable: false', compiler)
        self.assertNotIn('install_in_xbin:', compiler)
        self.assertFalse((OWNED / 'Android.mk').exists())
        for text in ('name: "overlay_remounter"', 'srcs: [":sheng_overlay_remounter"]',
                     'prefer: true', 'static_executable: true', 'install_in_xbin: true',
                     'soong_config_variable("sheng", "first_stage_rootfix")',
                     'default: false'):
            self.assertIn(text, installer)
        for bypass in ('check_elf_files: false', 'allow_undefined_symbols: true',
                       'overrides:', '.intermediates/'):
            self.assertNotIn(bypass, installer)

    def test_policy_is_included_and_not_permissive(self):
        directory = 'interfaces/compat/overlay-remounter/sepolicy/system_ext/private'
        self.assertIn('SYSTEM_EXT_PRIVATE_SEPOLICY_DIRS += $(DEVICE_PATH)/' + directory,
                      (DEVICE / 'BoardConfig.mk').read_text())
        policy = (OWNED / 'sepolicy/system_ext/private/sheng_overlay_remounter.te').read_text()
        self.assertIn('userdebug_or_eng(`', policy)
        self.assertNotRegex(policy, r'\bpermissive\b')
        self.assertNotIn('setenforce', policy)

    def test_context_does_not_match_nearby_names(self):
        context = (OWNED / 'sepolicy/system_ext/private/file_contexts').read_text().split()[0]
        for path in ('/second_stage_resources/sheng-remount',
                     '/second_stage_resources/sheng-remount/67'):
            self.assertIsNotNone(re.fullmatch(context, path))
        for path in ('/second_stage_resources/overlay_remounter',
                     '/second_stage_resources/sheng-remount-other', '/system/bin/init'):
            self.assertIsNone(re.fullmatch(context, path))

    def test_magisk_tmpfs_file_metadata_only(self):
        policy = (OWNED / 'sepolicy/system_ext/private/sheng_overlay_remounter.te').read_text()
        policy = re.sub(r'#[^\n]*', '', policy)
        rules = re.findall(r'allow\s+overlay_remounter\s+tmpfs:file\s+([^;]+);', policy)
        self.assertEqual(rules, ['getattr'])
        # The handoff preserves the original bind-mounted inode and its label;
        # only dedicated holders receive the staging type.
        helper = (OWNED / 'mount_preserver.h').read_text()
        self.assertIn('MS_MOVE', helper)
        for relabel in ('setfilecon(', 'restorecon(', 'setxattr('):
            self.assertNotIn(relabel, helper)


if __name__ == '__main__':
    unittest.main()
