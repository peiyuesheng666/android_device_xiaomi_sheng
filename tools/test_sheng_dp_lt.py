#!/usr/bin/env python3
"""Compare sheng tuning with the retained original driver and exercise its gate."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--reference', type=Path, required=True)
args = parser.parse_args()
device = Path(__file__).resolve().parents[1]
header = (device / 'interfaces/kernel/6.18/sheng_dp_legacy_lt.h').read_text()
reference = args.reference.read_text()

def values(source, name):
    body = re.search(r'\b' + name + r'\[[^=]+?=\s*\{(.*?)\n\s*\};', source, re.S).group(1)
    body = re.sub(r'/\*.*?\*/', '', body, flags=re.S)
    result = [int(x, 16) for x in re.findall(r'0x[0-9a-fA-F]+', body)]
    assert len(result) == 16
    return result

tables = [('swing_high', 'dp_swing_hbr2_hbr3'), ('emp_high', 'dp_pre_emp_hbr2_hbr3'),
          ('swing_low', 'dp_swing_hbr_rbr'), ('emp_low', 'dp_pre_emp_hbr_rbr_v600')]
expected = {}
for new, old in tables:
    expected[new] = values(reference, old)
    assert values(header, new) == expected[new], new
prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
typedef uint8_t u8;
typedef uint32_t u32;
static int root;
static void *of_root = &root;
static int model_match;
static int of_property_match_string(void *n, const char *k, const char *v) { return model_match; }
'''
source = prefix + header.replace('#include <linux/of.h>', '')
for name, _ in tables:
    source += 'static const u8 expected_' + name + '[16] = {' + ','.join(map(str, expected[name])) + '};\n'
source += r'''
int main(void) {
    u8 s = 0, p = 0;
    for (int high = 0; high <= 1; ++high)
        for (int v = 0; v < 4; ++v)
            for (int e = 0; e < 4; ++e) {
                assert(sheng_dp_legacy_lt_values(0x10020003, 0x60000000, v, e, high, &s, &p));
                assert(s == (high ? expected_swing_high : expected_swing_low)[v * 4 + e]);
                assert(p == (high ? expected_emp_high : expected_emp_low)[v * 4 + e]);
            }
    assert(!sheng_dp_legacy_lt_values(0x10020002, 0x60000000, 0, 0, true, &s, &p));
    assert(!sheng_dp_legacy_lt_values(0x10020003, 0x50000000, 0, 0, true, &s, &p));
    assert(!sheng_dp_legacy_lt_values(0x10020003, 0x70000000, 0, 0, true, &s, &p));
    assert(!sheng_dp_legacy_lt_values(0x10020003, 0x60000000, 4, 0, true, &s, &p));
    assert(!sheng_dp_legacy_lt_values(0x10020003, 0x60000000, 0, 4, true, &s, &p));
    model_match = -1;
    assert(!sheng_dp_legacy_lt_values(0x10020003, 0x60000000, 0, 0, true, &s, &p));
    model_match = 0; of_root = 0;
    assert(!sheng_dp_legacy_lt_values(0x10020003, 0x60000000, 0, 0, true, &s, &p));
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='sheng-dp-lt-') as directory:
    c = Path(directory) / 'test.c'
    binary = Path(directory) / 'test'
    c.write_text(source)
    subprocess.run(['gcc', '-fsanitize=address,undefined', '-g', str(c), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print(json.dumps(dict(passed=True, reference=str(args.reference),
                      reference_sha256=hashlib.sha256(args.reference.read_bytes()).hexdigest(),
                      table_bytes_compared=64, actual_helper_exercised=True)))
