#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise boot-critical dependency loss and invalid depmod input cases."""
import unittest
from plan_sheng_kernel_modules import ModuleGraph


class ModulePlanTest(unittest.TestCase):
    def roots(self, first=(), recovery=(), system=(), vendor=()):
        return dict(first_stage=list(first), recovery=list(recovery),
                    system_dlkm=list(system), vendor_dlkm=list(vendor))

    def test_storage_dependency_is_in_first_stage(self):
        graph = ModuleGraph('kernel/ufs.ko: kernel/phy.ko\nkernel/phy.ko:\n'
                            'kernel/wifi.ko: kernel/phy.ko\n', '')
        plan = graph.plan(self.roots(first=['ufs'], vendor=['wifi']), {})
        self.assertEqual(plan['load']['first_stage'], ['kernel/phy.ko', 'kernel/ufs.ko'])
        self.assertEqual(plan['install']['vendor_dlkm'],
                         ['kernel/phy.ko', 'kernel/ufs.ko', 'kernel/wifi.ko'])
        self.assertEqual(plan['load']['vendor_dlkm'], ['kernel/phy.ko', 'kernel/wifi.ko'])

    def test_first_stage_system_module_keeps_normal_dlkm_copy(self):
        graph = ModuleGraph('zram.ko: zsmalloc.ko\nzsmalloc.ko:\n', '')
        plan = graph.plan(self.roots(first=['zram'], system=['zram']), {})
        self.assertEqual(plan['install']['vendor_boot'], ['zsmalloc.ko', 'zram.ko'])
        self.assertEqual(plan['install']['system_dlkm'], ['zsmalloc.ko', 'zram.ko'])
        self.assertEqual(plan['install']['vendor_dlkm'], [])

    def test_recovery_only_driver_retained_for_android(self):
        graph = ModuleGraph('touch.ko: i2c.ko\ni2c.ko:\npen.ko: touch.ko\n', '')
        plan = graph.plan(self.roots(recovery=['touch'], vendor=['pen']), {})
        self.assertEqual(plan['install']['vendor_boot'], ['i2c.ko', 'touch.ko'])
        self.assertEqual(plan['load']['first_stage'], [])
        self.assertEqual(plan['load']['vendor_dlkm'], ['i2c.ko', 'touch.ko', 'pen.ko'])

    def test_builtin_root_has_no_fake_ko(self):
        graph = ModuleGraph('zram.ko:\n', 'mm/zsmalloc.ko\n')
        plan = graph.plan(self.roots(system=['zram', 'zsmalloc']), {})
        self.assertEqual(plan['install']['system_dlkm'], ['zram.ko'])
        self.assertEqual(plan['builtin_roots']['system_dlkm'], ['zsmalloc'])

    def test_soft_pre_and_post_order(self):
        graph = ModuleGraph('panel.ko:\nbus.ko:\nbacklight.ko:\n', '',
                            'softdep panel pre: bus post: backlight\n')
        plan = graph.plan(self.roots(recovery=['panel']), {})
        self.assertEqual(plan['load']['recovery'], ['bus.ko', 'panel.ko', 'backlight.ko'])

    def test_no_silent_missing_root(self):
        graph = ModuleGraph('new.ko:\n', '')
        with self.assertRaisesRegex(ValueError, 'Required module is missing'):
            graph.plan(self.roots(first=['old']), {})

    def test_path_traversal_rejected(self):
        for path in ('../bad.ko', '/bad.ko', 'kernel/../../bad.ko'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                ModuleGraph(path+':\n', '')

    def test_name_alias_collision_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            ModuleGraph('a/foo-bar.ko:\nb/foo_bar.ko:\n', '')

    def test_builtin_and_loadable_collision_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            ModuleGraph('usb.ko:\n', 'drivers/usb.ko\n')

    def test_missing_dependency_path_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unresolved dependency'):
            ModuleGraph('ufs.ko: missing/phy.ko\nphy.ko:\n', '')

    def test_missing_softdep_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unresolved softdep'):
            ModuleGraph('panel.ko:\n', '', 'softdep panel pre: bus\n')

    def test_cycle_rejected(self):
        graph = ModuleGraph('a.ko: b.ko\nb.ko: a.ko\n', '')
        with self.assertRaisesRegex(ValueError, 'Cyclic'):
            graph.plan(self.roots(first=['a']), {})

    def test_loader_exclusion_cannot_remove_dependency(self):
        graph = ModuleGraph('device.ko: loader.ko\nloader.ko:\n', '')
        with self.assertRaisesRegex(ValueError, 'Retained module depends'):
            graph.plan(self.roots(), {'loader': 'standalone loader'})

    def test_standalone_loader_excluded_explicitly(self):
        graph = ModuleGraph('device.ko:\nk618_load.ko:\n', '')
        plan = graph.plan(self.roots(vendor=['device']), {'k618_load': 'Android init owns loading'})
        self.assertEqual(plan['install']['vendor_dlkm'], ['device.ko'])

    def test_underscore_hyphen_alias_is_supported(self):
        graph = ModuleGraph('qcom-ipcc.ko:\n', '')
        plan = graph.plan(self.roots(first=['qcom_ipcc.ko']), {})
        self.assertEqual(plan['load']['first_stage'], ['qcom-ipcc.ko'])

    def optional(self):
        return [dict(owner='pinctrl_kalama', dependency='qcom_tlmm_vm_irqchip',
                     config='CONFIG_QCOM_TLMM_VM_IRQCHIP',
                     reason='Unconditional guest IRQ softdep; the guest IRQ driver is disabled')]

    def test_disabled_optional_softdep_is_recorded(self):
        graph = ModuleGraph('pinctrl-kalama.ko:\n', '',
                            'softdep pinctrl_kalama pre: qcom_tlmm_vm_irqchip\n',
                            self.optional(), '# CONFIG_QCOM_TLMM_VM_IRQCHIP is not set\n')
        plan = graph.plan(self.roots(first=['pinctrl_kalama']), {})
        self.assertEqual(plan['load']['first_stage'], ['pinctrl-kalama.ko'])
        self.assertEqual(plan['configured_optional_softdeps'], self.optional())

    def test_enabled_or_unknown_config_cannot_excuse_missing_softdep(self):
        for config in ('', 'CONFIG_QCOM_TLMM_VM_IRQCHIP=m\n', 'CONFIG_QCOM_TLMM_VM_IRQCHIP=y\n'):
            with self.subTest(config=config), self.assertRaisesRegex(ValueError, 'not explicitly disabled'):
                ModuleGraph('pinctrl-kalama.ko:\n', '',
                            'softdep pinctrl_kalama pre: qcom_tlmm_vm_irqchip\n', self.optional(), config)

    def test_optional_rule_cannot_excuse_hard_dependency(self):
        with self.assertRaisesRegex(ValueError, 'Unresolved dependency path'):
            ModuleGraph('pinctrl-kalama.ko: qcom_tlmm_vm_irqchip.ko\n', '', '',
                        self.optional(), '# CONFIG_QCOM_TLMM_VM_IRQCHIP is not set\n')

    def test_optional_rule_cannot_excuse_required_root(self):
        graph = ModuleGraph('pinctrl-kalama.ko:\n', '',
                            'softdep pinctrl_kalama pre: qcom_tlmm_vm_irqchip\n',
                            self.optional(), '# CONFIG_QCOM_TLMM_VM_IRQCHIP is not set\n')
        with self.assertRaisesRegex(ValueError, 'Required module is missing'):
            graph.plan(self.roots(first=['qcom_tlmm_vm_irqchip']), {})

    def test_optional_rule_becomes_invalid_when_module_is_present(self):
        with self.assertRaisesRegex(ValueError, 'Stale or ambiguous'):
            ModuleGraph('pinctrl-kalama.ko:\nqcom_tlmm_vm_irqchip.ko:\n', '', '',
                        self.optional(), '# CONFIG_QCOM_TLMM_VM_IRQCHIP is not set\n')

    def test_optional_rule_for_another_inventory_rejected(self):
        with self.assertRaisesRegex(ValueError, 'do not match'):
            ModuleGraph('pinctrl-kalama.ko:\n', '', '', self.optional(),
                        '# CONFIG_QCOM_TLMM_VM_IRQCHIP is not set\n')


if __name__ == '__main__':
    unittest.main()
