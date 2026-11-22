import unittest
from pathlib import Path

from build_source_variants import rebase_local_includes


class IncludeTests(unittest.TestCase):
    def test_local_only_not_dependency_exports(self):
        old = '-Isystem/fs/fs_mgr -Isystem/fs/fs_mgr/include -Isystem/fs/fs_mgr/libfstab/include -Isystem/fs/fs_mgr/libfs_avb/include'
        new = rebase_local_includes(old, {'system/fs/fs_mgr': 'device/owned'})
        self.assertEqual(new, '-Idevice/owned -Idevice/owned/include -Isystem/fs/fs_mgr/libfstab/include -Isystem/fs/fs_mgr/libfs_avb/include')

    def test_does_not_match_neighbor_or_embedded_path(self):
        old = '-Isystem/core/init-other -Iprefix/system/core/init -Isystem/core/init'
        self.assertEqual(rebase_local_includes(old, {'system/core/init': 'device/owned'}),
                         '-Isystem/core/init-other -Iprefix/system/core/init -Idevice/owned')


class DependencyContractTests(unittest.TestCase):
    def test_snapshot_does_not_reintroduce_stock_fs_mgr(self):
        device = Path(__file__).resolve().parents[2]
        init = (device / 'interfaces/compat/first-stage-init/Android.bp').read_text()
        snapshot = (device / 'interfaces/compat/snapshot-first-stage/Android.bp').read_text()
        self.assertIn('"libsheng_snapshot_init"', init)
        self.assertNotIn('"libsnapshot_init"', init)
        self.assertIn('exclude_static_libs: ["libfs_mgr", "libcrypto_static", "libunwindstack_no_dex"]', init)
        self.assertIn('defaults: ["libsnapshot_defaults"]', snapshot)
        self.assertIn('srcs: [":libsnapshot_sources"]', snapshot)
        self.assertIn('"libsheng_fs_mgr_first_stage"', snapshot)
        self.assertIn('exclude_shared_libs: ["libchrome"]', snapshot)
        self.assertNotIn('"libfs_mgr"', snapshot)
        self.assertNotIn('whole_static_libs', init + snapshot)

    def test_root_installer_uses_compiled_input_without_neverallow_exception(self):
        device = Path(__file__).resolve().parents[2]
        init = (device / 'interfaces/compat/first-stage-init/Android.bp').read_text()
        compiler, installer = init.split('cc_prebuilt_binary {', 1)
        self.assertIn('install_in_root: false', compiler)
        self.assertIn('installable: false', compiler)
        self.assertNotIn('overrides:', compiler)
        self.assertIn('srcs: [":sheng_init_first_stage"]', installer)
        self.assertIn('install_in_root: true', installer)
        self.assertIn('ramdisk: true', installer)
        self.assertIn('name: "init_first_stage"', installer)
        self.assertIn('prefer: true', installer)
        self.assertIn('soong_config_variable("sheng", "first_stage_rootfix")', installer)
        self.assertNotIn('overrides:', installer)
        product = (device / 'interfaces/compat/first-stage-init/product.mk').read_text()
        self.assertIn('PRODUCT_PACKAGES_DEBUG += init_first_stage', product)
        self.assertIn('$(call soong_config_set,sheng,first_stage_rootfix,', product)

    def test_required_private_functionality_is_not_removed(self):
        device = Path(__file__).resolve().parents[2]
        root = device / 'interfaces/compat'
        init = (root / 'first-stage-init/Android.bp').read_text()
        for lib in ('libsheng_crypto_first_stage', 'libsheng_unwind_first_stage',
                    'libsheng_zstd_first_stage'):
            self.assertIn('"' + lib + '"', init)
        crypto = (root / 'first-stage-crypto/Android.bp').read_text()
        for default in ('libcrypto_bcm_sources', 'libcrypto_sources', 'libcrypto_defaults',
                        'boringssl_defaults', 'boringssl_flags'):
            self.assertIn('"sheng_first_stage_' + default + '"', crypto)
        unwind = (root / 'first-stage-unwind/Android.bp').read_text()
        self.assertIn('"sheng_first_stage_libunwindstack_defaults", "rust_static_std"', unwind)
        defaults = (root / 'first-stage-unwind/defaults.bp').read_text()
        self.assertIn('"libsheng_zstd_first_stage"', defaults)
        self.assertIn('"libsheng_bionic_platform_headers"', defaults)
        self.assertNotIn('DEXFILE_SUPPORT', unwind)
        self.assertIn('defaults: ["zstd_defaults"]',
                      (root / 'first-stage-zstd/Android.bp').read_text())


if __name__ == '__main__':
    unittest.main()
