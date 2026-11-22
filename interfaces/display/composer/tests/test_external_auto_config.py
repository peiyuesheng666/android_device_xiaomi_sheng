#!/usr/bin/env python3
"""Exercise production UpdateConfigs with sparse raw IDs and duplicate modes."""
from pathlib import Path
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[1] / 'hwc_display.cpp').read_text()
start = source.index('void HWCDisplay::UpdateConfigs()')
opening = source.index('{', start)
end, depth = opening + 1, 1
while depth:
    depth += (source[end] == '{') - (source[end] == '}')
    end += 1
body = source[start:end]
harness = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <map>
#include <vector>
using hwc2_config_t = uint32_t;
#define UINT32(x) static_cast<uint32_t>(x)
#define INT(x) static_cast<int>(x)
#define DLOGI(...) ((void)0)
#define DLOGE(...) ((void)0)
enum { kBuiltIn, kPluggable };
struct DisplayConfigVariableInfo {
  uint32_t x_pixels=0, y_pixels=0, fps=0;
  bool operator==(const DisplayConfigVariableInfo &o) const {
    return x_pixels==o.x_pixels && y_pixels==o.y_pixels && fps==o.fps;
  }
};
struct HWCDisplay {
  int type_=kPluggable;
  uint32_t num_configs_=4, raw_active=3, active_index=99;
  std::vector<uint32_t> hwc_config_map_;
  std::map<uint32_t,DisplayConfigVariableInfo> variable_config_map_;
  std::vector<DisplayConfigVariableInfo> modes = {
    {3840,2160,30}, {4096,2160,30}, {1920,1080,60}, {1920,1080,60}
  };
  void GetDisplayAttributesForConfig(int i, DisplayConfigVariableInfo *out) {
    *out=modes.at(i);
  }
  void GetActiveConfig(uint32_t *out) { *out=hwc_config_map_.at(raw_active); }
  void SetActiveConfigIndex(uint32_t index) { active_index=index; }
  void UpdateConfigs();
};
'''
main = r'''
int main() {
  HWCDisplay external;
  external.UpdateConfigs();
  assert(external.num_configs_==1);
  assert(external.variable_config_map_.count(2)==1);
  assert(external.active_index==2);
  assert(external.hwc_config_map_.size()==4);
  assert(external.hwc_config_map_.at(3)==2);
  assert(external.variable_config_map_.at(2).fps==60);
  HWCDisplay builtin;
  builtin.type_=kBuiltIn;
  builtin.UpdateConfigs();
  assert(builtin.num_configs_==3);
  assert(builtin.variable_config_map_.count(0)==1);
  assert(builtin.variable_config_map_.count(1)==1);
  HWCDisplay empty;
  empty.num_configs_=0;
  empty.UpdateConfigs();
  assert(empty.variable_config_map_.empty());
}
'''
with tempfile.TemporaryDirectory(prefix='sheng-external-config-test-') as folder:
    cpp = Path(folder) / 'test.cpp'
    exe = Path(folder) / 'test'
    cpp.write_text(harness + body + main)
    subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(cpp),
                    '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('PASS: production external mode filtering, duplicate raw IDs, built-in and empty modes')
