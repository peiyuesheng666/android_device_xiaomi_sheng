import unittest
from sheng_kernel_log import kernel_errors


class KernelLogTests(unittest.TestCase):
    def test_driver_names_are_not_crashes(self):
        self.assertEqual(kernel_errors('ramoops: using 0x400000@0xa7000000\nspmi_pmic_arb_debug: SPMI debug bus disabled by fuse'), [])

    def test_crashes_remain_fail_closed(self):
        for message in ('BUG: unable to handle kernel', 'Oops: 00000000', 'Kernel panic - not syncing',
                        'qti: Unknown symbol test', 'disagrees about version of symbol foo',
                        'invalid module format', 'module verification failed',
                        'Kernel module BTF mismatch detected'):
            with self.subTest(message=message):
                self.assertEqual(kernel_errors('[1.2] '+message), ['[1.2] '+message])


if __name__ == '__main__':
    unittest.main()
