#!/usr/bin/env python3
"""Exercise production SetActiveConfig with a fake modesetting backend."""
import pathlib
import subprocess
import tempfile

source = (pathlib.Path(__file__).resolve().parents[2] / 'core/display_base.cpp').read_text()
start = source.index('DisplayError DisplayBase::SetActiveConfig(uint32_t index)')
opening = source.index('{', start)
end, depth = opening + 1, 1
while depth:
    depth += (source[end] == '{') - (source[end] == '}')
    end += 1
production = source[start:end]
harness = r'''
#include <cassert>
#include <cstdint>
#include <vector>
enum DisplayError { kErrorNone, kErrorFailed };
enum DisplayType { kBuiltIn, kPluggable };
struct HWDisplayAttributes { unsigned fps=30; };
struct Backend {
  unsigned active=0;
  bool subscribed=true, fail_mode=false;
  std::vector<int> calls;
  DisplayError GetActiveConfig(uint32_t *i) { *i=active; return kErrorNone; }
  DisplayError GetDisplayAttributes(uint32_t, HWDisplayAttributes *) { return kErrorNone; }
  DisplayError SetDisplayAttributes(uint32_t i) {
    calls.push_back(2);
    // A full external modeset must not race an enabled one-shot subscription.
    assert(!subscribed);
    if (fail_mode) return kErrorFailed;
    active=i;
    return kErrorNone;
  }
};
struct ClientLock { explicit ClientLock(int &) {} };
struct DisplayBase {
  int disp_mutex_=0;
  bool validated_=true, avoid_qsync_mode_change_=false;
  bool vsync_enable_=true, vsync_enable_pending_=false;
  bool fail_disable=false;
  unsigned active_refresh_rate_=0;
  DisplayType display_type_=kPluggable;
  Backend backend;
  Backend *hw_intf_=&backend;
  DisplayError SetVSyncStateLocked(bool enabled) {
    backend.calls.push_back(enabled ? 3 : 1);
    if (!enabled && fail_disable) return kErrorFailed;
    vsync_enable_=enabled;
    backend.subscribed=enabled;
    if (!enabled) vsync_enable_pending_=false;
    return kErrorNone;
  }
  DisplayError ReconfigureDisplay() { backend.calls.push_back(4); return kErrorNone; }
  DisplayError SetActiveConfig(uint32_t index);
};
''' + production + r'''
int main() {
  DisplayBase d;
  assert(d.SetActiveConfig(1)==kErrorNone);
  assert((d.backend.calls==std::vector<int>{1,2,4}));
  assert(!d.vsync_enable_ && d.vsync_enable_pending_);
  // Same mode: do not interrupt VSync or schedule another resume.
  DisplayBase same;
  assert(same.SetActiveConfig(0)==kErrorNone && same.backend.calls.empty());
  assert(same.vsync_enable_ && !same.vsync_enable_pending_);
  // Failed attribute change: restore the old subscription and propagate error.
  DisplayBase failed;
  failed.backend.fail_mode=true;
  assert(failed.SetActiveConfig(1)==kErrorFailed);
  assert((failed.backend.calls==std::vector<int>{1,2,3}));
  assert(failed.vsync_enable_ && !failed.vsync_enable_pending_);
  // Failed pause: never proceed with an unsafe modeset.
  DisplayBase pause;
  pause.fail_disable=true;
  assert(pause.SetActiveConfig(1)==kErrorFailed);
  assert((pause.backend.calls==std::vector<int>{1}));
  // No subscription requested: do not enable one as a side effect.
  DisplayBase off;
  off.vsync_enable_=false;
  off.backend.subscribed=false;
  assert(off.SetActiveConfig(1)==kErrorNone);
  assert(!off.vsync_enable_pending_);
  // Built-in same-config behavior must remain untouched.
  DisplayBase internal;
  internal.display_type_=kBuiltIn;
  assert(internal.SetActiveConfig(0)==kErrorNone && internal.backend.calls.empty());
}
'''
with tempfile.TemporaryDirectory(prefix='sheng-dp-vsync-') as tmp:
    cpp, exe = pathlib.Path(tmp)/'test.cpp', pathlib.Path(tmp)/'test'
    cpp.write_text(harness)
    subprocess.run(['g++', '-std=c++17', '-Wall', '-Werror', str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('PASS: external modeset VSync pause, deferred resume, failure and idle paths')
