#!/usr/bin/env python3
"""Synthetic parser tests; not hardware acceptance."""
import unittest
from summarize_sheng_dp_writes import decode


class DecodeTests(unittest.TestCase):
    def test_empty_is_not_positive(self):
        self.assertFalse(decode('# entries-in-buffer: 0')['positive_write_coverage'])
        self.assertFalse(decode('')['clock_mn_write_coverage'])

    def test_clock_coverage_requires_both_writes(self):
        m = ' x 1.0: hw_write: bank="dp_link" off=0x10 val=0x1234'
        n = ' x 1.1: hw_write: bank="dp_link" off=24 val=32768'
        self.assertFalse(decode(m)['clock_mn_write_coverage'])
        self.assertFalse(decode(n)['clock_mn_write_coverage'])
        result = decode(m + '\n' + n)
        self.assertTrue(result['clock_mn_write_coverage'])
        self.assertEqual(result['last_observed_arguments']['dp_link.SOFTWARE_MVID'], '0x1234')
        self.assertEqual(result['last_observed_arguments']['dp_link.SOFTWARE_NVID'], '0x8000')

    def test_order_and_last_value(self):
        trace = '\n'.join([
            ' worker-1 [000] ..... 1.000001: hw_write: (dp_write_hw+0x0/0x20 [msm_drm]) bank="dp_link" off=588 val=1',
            ' worker-1 [000] ..... 1.000002: hw_write: (dp_write_hw+0x0/0x20 [msm_drm]) bank="dp_link" off=0x24c val=0x0',
            ' worker-1 [000] ..... 1.000003: hw_write: (dp_write_hw+0x0/0x20 [msm_drm]) bank="dp_p0" off=20 val=16',
        ])
        result = decode(trace)
        self.assertEqual(result['write_events'], 3)
        self.assertEqual([e['value'] for e in result['events']], ['0x1', '0x0', '0x10'])
        self.assertEqual(result['last_observed_arguments']['dp_link.SDP_CFG3'], '0x0')

    def test_unknown_register_rejected(self):
        with self.assertRaises(ValueError):
            decode(' x 1.0: hw_write: bank="dp_aux" off=0 val=0')

    def test_unrelated_events_ignored(self):
        self.assertEqual(decode(' x 1.0: ctrl: cfg=16983')['write_events'], 0)


if __name__ == '__main__':
    unittest.main()
