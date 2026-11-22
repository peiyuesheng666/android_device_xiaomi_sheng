#!/usr/bin/env python3
"""Test actual diagnostic branch with fake MMIO; not hardware acceptance."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--display', type=Path, required=True)
a = p.parse_args()
source = (a.display / 'msm/dp/dp_catalog.c').read_text()
start = source.index('\t/* Stream 0 only; no interrupt, AUX, PHY, MISR, or whole-bank reads. */')
end = source.index('\n}\n\nstatic void dp_catalog_panel_setup_vsif', start)
branch = source[start:end]
registers = re.findall(r'^#define\s+(\w+)\s+\((0x[0-9A-Fa-f]+)\)',
                       (a.display / 'msm/dp/dp_reg.h').read_text(), re.M)
names = set(re.findall(r'\b(?:DP_|MMSS_DP_)[A-Z0-9_]+\b', branch)) - {'DP_INFO', 'DP_STREAM_0'}
definitions = {name: int(value, 16) for name, value in registers if name in names}
assert len(definitions) == 19 and len(names) == 19
prefix = '''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
typedef uint32_t u32;
#define READ_ONCE(x) (x)
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define DP_STREAM_0 0
#define DP_INFO(fmt,off,val) do { (void)(off); (void)(val); } while(0)
static bool sheng_dp_color_readback;
static unsigned count, limit;
static u32 fake_read(u32 offset) { assert(offset+4 <= limit); count++; return 0; }
#define dp_read(offset) fake_read(offset)
struct panel { int stream_id; };
struct catalog { const char *exe_mode; };
struct io { struct { void *base; u32 len; } io; };
static void exercise(struct panel *panel, struct catalog *catalog, struct io *io_data) {
'''
defines = ''.join(f'#define {name} {value}\n' for name, value in definitions.items())
offsets = ','.join(map(str, definitions.values()))
suffix = '''
}
int main(void) {
 const char *modes[] = {"hw", "all", "sw", "invalid"};
 unsigned lengths[] = {0,4,48,796,804};
 unsigned offsets[] = {OFFSETS};
 unsigned cases=0;
 for(int enabled=0;enabled<2;enabled++)
 for(int stream=0;stream<2;stream++)
 for(unsigned m=0;m<4;m++)
 for(unsigned l=0;l<5;l++)
 for(int base=0;base<2;base++) {
  struct panel panel={stream}; struct catalog catalog={modes[m]};
  struct io io={.io={.base=base ? &cases : 0, .len=lengths[l]}};
  sheng_dp_color_readback=enabled; count=0; limit=lengths[l];
  exercise(&panel,&catalog,&io);
  unsigned expected=0;
  if(enabled && !stream && m<2 && base)
   for(unsigned i=0;i<19;i++) expected += offsets[i]+4 <= limit;
  assert(count == expected); cases++;
 }
 assert(cases == 160); return 0;
}
'''.replace('OFFSETS', offsets)
with tempfile.TemporaryDirectory(prefix='sheng-dp-readback-test-') as tmp:
    c = Path(tmp) / 'test.c'
    binary = Path(tmp) / 'test'
    c.write_text(defines + prefix + branch + suffix)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', str(c), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('PASS: 160 actual-branch fake-MMIO cases; default off, mode, stream, base and bounds')
