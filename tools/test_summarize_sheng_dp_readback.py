#!/usr/bin/env python3
import unittest
from summarize_sheng_dp_readback import decode, OFFSETS


def fixture(offsets=OFFSETS):
    return '\n'.join(f'[ 1.000001] sheng_dp_rb link off={off:#x} value={0x4380780 if off == 40 else 0:#x}'
                     for off in offsets)


class ReadbackTest(unittest.TestCase):
    def test_complete(self):
        item = decode(fixture())['snapshots'][0]
        self.assertTrue(item['complete'])
        self.assertEqual((item['width'], item['height']), (1920, 1080))

    def test_missing(self):
        self.assertFalse(decode(fixture(OFFSETS[:-1]))['snapshots'][0]['complete'])

    def test_order(self):
        order = list(OFFSETS)
        order[1], order[2] = order[2], order[1]
        self.assertFalse(decode(fixture(order))['snapshots'][0]['complete'])

    def test_multiple(self):
        items = decode(fixture() + '\n' + fixture())['snapshots']
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item['complete'] for item in items))

    def test_empty(self):
        self.assertEqual(decode('unrelated log')['snapshots'], [])

    def test_older_ring_buffer(self):
        self.assertEqual(decode(fixture(), since=2.0)['snapshots'], [])
        self.assertTrue(decode(fixture(), since=1.0)['snapshots'][0]['complete'])


if __name__ == '__main__':
    unittest.main()
