# SPDX-License-Identifier: Apache-2.0
"""Read one measured native host snapshot without relaxing resource freshness."""
from datetime import datetime
import json
import re
import time


def read_host_sample(identity, *, sample_path=None, sample_directory=None, now=None):
    if (sample_path is None) == (sample_directory is None):
        raise ValueError('Select exactly one native sample source')
    sequence = None
    if sample_directory is not None:
        candidates = [(int(match[1]), path) for path in sample_directory.iterdir()
                      if (match := re.fullmatch(r'sample-(\d{10})\.json', path.name))]
        if not candidates:
            raise RuntimeError('No published native host memory sample')
        sequence, sample_path = max(candidates)
    sample = json.loads(sample_path.read_text(encoding='utf-8-sig'))
    age = (time.time() if now is None else now) - datetime.fromisoformat(
        sample['date_utc'].replace('Z', '+00:00')).timestamp()
    if sample['identity'] != identity or not -3 <= age <= 10:
        raise RuntimeError('Native host memory sample is stale or belongs to another build')
    if not all(type(sample[key]) is int and sample[key] > 0
               for key in ('free_commit_bytes', 'c_free_bytes', 'monitor_pid', 'sequence')):
        raise RuntimeError('Native host memory sample is invalid')
    if sequence is not None and sample['sequence'] != sequence:
        raise RuntimeError('Native host memory sample sequence does not match its filename')
    return sample
