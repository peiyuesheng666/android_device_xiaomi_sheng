#!/usr/bin/env python3
"""Exercise the actual driver's downshift function with host-side DP state."""
import argparse
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=Path)
args = parser.parse_args()
source = args.source.read_text()
start = source.index('static int dp_ctrl_link_rate_down_shift(')
end = source.index('\nstatic ', start + 1)
function = source[start:end]
prefix = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#define u8 uint8_t
#define EINVAL 22
#define DP_LINK_BW_8_1 30
#define DP_LINK_BW_5_4 20
#define DP_LINK_BW_2_7 10
#define DP_LINK_BW_1_62 6
#define DP_DEBUG(...) ((void)0)
static int model_matches = 1;
static void *of_root = (void *)1;
static int of_property_match_string(void *a, const char *b, const char *c) {
  (void)a; (void)b; (void)c; return model_matches ? 0 : -1;
}
struct params { u8 bw_code, lane_count; };
struct dp_link { struct params link_params; };
struct dp_ctrl_private { struct dp_link *link; u8 initial_lane_count; };
'''
main = r'''
int main(void) {
  struct dp_link link = {{20, 1}};
  struct dp_ctrl_private ctrl = {&link, 2};
  assert(dp_ctrl_link_rate_down_shift(NULL) == -EINVAL);
  assert(dp_ctrl_link_rate_down_shift(&ctrl) == 0);
  assert(link.link_params.bw_code == 10 && link.link_params.lane_count == 2);
  link.link_params = (struct params){10, 1};
  dp_ctrl_link_rate_down_shift(&ctrl);
  assert(link.link_params.bw_code == 6 && link.link_params.lane_count == 2);
  // At the lowest rate, do not keep restoring lanes and looping indefinitely.
  link.link_params = (struct params){6, 1};
  dp_ctrl_link_rate_down_shift(&ctrl);
  assert(link.link_params.bw_code == 6 && link.link_params.lane_count == 1);
  model_matches = 0;
  link.link_params = (struct params){20, 1};
  dp_ctrl_link_rate_down_shift(&ctrl);
  assert(link.link_params.bw_code == 10 && link.link_params.lane_count == 1);
  model_matches = 1; of_root = NULL;
  link.link_params = (struct params){20, 1};
  dp_ctrl_link_rate_down_shift(&ctrl);
  assert(link.link_params.lane_count == 1);
  return 0;
}
'''
with tempfile.TemporaryDirectory() as directory:
    c = Path(directory) / 'test.c'
    binary = Path(directory) / 'test'
    c.write_text(prefix + function + main)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    str(c), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
setup = source[source.index('static int dp_ctrl_link_setup('):]
loop = setup[setup.index('while (1) {'):]
assert loop.index('catalog->phy_lane_cfg(') < loop.index('dp_ctrl_enable_link_clock(')
print('DP lane retry state and PHY metadata ordering passed')
