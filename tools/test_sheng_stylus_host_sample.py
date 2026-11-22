# SPDX-License-Identifier: Apache-2.0
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from sheng_stylus_host_sample import read_host_sample


class HostSampleTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.now = datetime.now(timezone.utc).timestamp()

    def publish(self, sequence, *, seconds_ago=0, **changes):
        sample = dict(identity='test', sequence=sequence, monitor_pid=123,
                      free_commit_bytes=4*1024**3, c_free_bytes=8*1024**3,
                      date_utc=datetime.fromtimestamp(self.now-seconds_ago, timezone.utc).isoformat())
        sample.update(changes)
        path = self.directory/f'sample-{sequence:010d}.json'
        path.write_text(json.dumps(sample))
        return path

    def read(self):
        return read_host_sample('test', sample_directory=self.directory, now=self.now)

    def test_old_reader_does_not_prevent_new_sample_selection(self):
        old = self.publish(1, seconds_ago=60)
        with old.open() as held_reader:
            self.publish(2)
            self.assertEqual(self.read()['sequence'], 2)
            self.assertEqual(json.load(held_reader)['sequence'], 1)

    def test_stale_latest_sample_is_rejected(self):
        self.publish(1)
        self.publish(2, seconds_ago=11)
        with self.assertRaisesRegex(RuntimeError, 'stale'):
            self.read()

    def test_wrong_build_identity_is_rejected(self):
        self.publish(1, identity='other-build')
        with self.assertRaisesRegex(RuntimeError, 'another build'):
            self.read()

    def test_future_clock_sample_is_rejected(self):
        self.publish(1, seconds_ago=-4)
        with self.assertRaisesRegex(RuntimeError, 'stale'):
            self.read()

    def test_invalid_memory_is_rejected(self):
        self.publish(1, free_commit_bytes=True)
        with self.assertRaisesRegex(RuntimeError, 'invalid'):
            self.read()

    def test_filename_sequence_must_match(self):
        path = self.publish(1)
        path.rename(self.directory/'sample-0000000002.json')
        with self.assertRaisesRegex(RuntimeError, 'sequence'):
            self.read()

    def test_incomplete_temporary_file_is_ignored(self):
        (self.directory/'sample.writing').write_text('{')
        with self.assertRaisesRegex(RuntimeError, 'No published'):
            self.read()


if __name__ == '__main__':
    unittest.main()
