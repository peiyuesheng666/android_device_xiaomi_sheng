#!/usr/bin/env python3
"""Host regression test of production pending-mode/geometry transition bodies.

Uses a fake display interface, not a substitute for linked/device DP tests.
"""
import pathlib
import subprocess
import tempfile

source = (pathlib.Path(__file__).resolve().parents[1] / "hwc_display.cpp").read_text()


def body(signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


harness = r'''
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <vector>
using hwc2_config_t = uint32_t;
namespace HWC2 { enum class Error { None, BadConfig, BadParameter, BadDisplay }; }
enum DisplayError { kErrorNone, kErrorDeferred, kErrorFailed };
#define DTRACE_SCOPED() ((void)0)
#define DLOGI(...) ((void)0)
#define DLOGW(...) ((void)0)
#define DLOGE(...) ((void)0)
#define DLOGV(...) ((void)0)
#define INT(x) static_cast<int>(x)
#define UINT32(x) static_cast<uint32_t>(x)
#define FLOAT(x) static_cast<float>(x)
struct DisplayConfigVariableInfo { uint32_t x_pixels, y_pixels; float fps; };
struct LayerRect {
  float left=0, top=0, right=0, bottom=0;
  LayerRect() = default;
  LayerRect(float l, float t, float r, float b):left(l),top(t),right(r),bottom(b) {}
};
struct hwc_rect_t { int left, top, right, bottom; };
struct Target {
  LayerRect src_rect;
  hwc_rect_t frame = {};
  int resets=0;
  Target *GetSDMLayer() { return this; }
  void SetLayerDisplayFrame(hwc_rect_t value) { frame=value; }
  void ResetPerFrameData() { ++resets; }
};
struct Display {
  uint32_t active = 0;
  DisplayError result = kErrorNone;
  DisplayConfigVariableInfo framebuffer = {3840,2160,30};
  DisplayError GetFrameBufferConfig(DisplayConfigVariableInfo *v) {
    *v=framebuffer; return kErrorNone;
  }
  DisplayError SetFrameBufferConfig(DisplayConfigVariableInfo v) {
    framebuffer=v; return kErrorNone;
  }
  DisplayError SetActiveConfig(uint32_t config) {
    if (result == kErrorNone) active = config;
    return result;
  }
};
struct HWCDisplay {
  Display display;
  Display *display_intf_ = &display;
  bool pending_config_ = true;
  uint32_t pending_config_index_ = 1;
  std::vector<uint32_t> hwc_config_map_ = {10, 11, 12};
  float active_refresh_rate_ = 0;
  int resize_count = 0;
  uint32_t width = 3840, height = 2160;
  Target target;
  Target *client_target_=&target;
  bool windowed_display_=false;
  LayerRect window_rect_;
  void ApplyScanAdjustment(hwc_rect_t *) {}
  int SetFrameBufferConfig(uint32_t, uint32_t);
  int GetActiveDisplayConfig(uint32_t *v) { *v = display.active; return 0; }
  void SetActiveConfigIndex(uint32_t) {}
  void GetDisplayAttributesForConfig(int i, DisplayConfigVariableInfo *v) {
    *v = i == 0 ? DisplayConfigVariableInfo{3840,2160,30} :
         DisplayConfigVariableInfo{1920,1080,i == 1 ? 30.f : 60.f};
  }
  int SetFrameBufferResolution(uint32_t w, uint32_t h) {
    int error=SetFrameBufferConfig(w,h);
    if (error) return error;
    width=w; height=h; ++resize_count; return 0;
  }
  HWC2::Error GetActiveConfig(hwc2_config_t *);
  HWC2::Error SubmitDisplayConfig(hwc2_config_t, bool *deferred = nullptr);
  void UpdateActiveConfig();
};
'''
harness += "\n".join(body(s) for s in (
    "HWC2::Error HWCDisplay::GetActiveConfig(",
    "HWC2::Error HWCDisplay::SubmitDisplayConfig(",
    "int HWCDisplay::SetFrameBufferConfig(",
    "void HWCDisplay::UpdateActiveConfig("))
harness += r'''
int main() {
  HWCDisplay d;
  d.UpdateActiveConfig();
  assert(d.width == 1920 && d.height == 1080 && d.resize_count == 1);
  assert(d.target.src_rect.right == 1920 && d.target.src_rect.bottom == 1080);
  assert(d.target.frame.right == 1920 && d.target.frame.bottom == 1080);
  assert(d.target.resets == 1);
  assert(!d.pending_config_ && d.display.active == 1);
  d.pending_config_=true; d.pending_config_index_=0;
  d.UpdateActiveConfig();
  assert(d.width == 3840 && d.height == 2160 && d.resize_count == 2);
  assert(d.target.src_rect.right == 3840 && d.target.src_rect.bottom == 2160);
  d.display.active=1; d.pending_config_=true; d.pending_config_index_=2;
  d.UpdateActiveConfig();
  assert(d.resize_count == 2); // refresh-only transition
  assert(d.target.resets == 2); // no redundant crop update on refresh change
  d.pending_config_=true; d.pending_config_index_=0;
  d.display.result=kErrorDeferred;
  d.UpdateActiveConfig();
  assert(d.display.active == 2 && d.resize_count == 2);
  assert(d.pending_config_); // deferred request must survive validation
  d.display.result=kErrorNone;
  d.UpdateActiveConfig();
  assert(d.display.active == 0 && d.resize_count == 3);
  assert(!d.pending_config_);
  d.UpdateActiveConfig();
  assert(d.resize_count == 3); // no pending transition
  d.pending_config_=true; d.pending_config_index_=1;
  d.display.result=kErrorFailed;
  d.UpdateActiveConfig();
  assert(!d.pending_config_ && d.resize_count == 3); // do not loop on hard failure
}
'''
with tempfile.TemporaryDirectory(prefix="sheng-dp-geometry-") as tmp:
    cpp = pathlib.Path(tmp) / "test.cpp"
    exe = pathlib.Path(tmp) / "test"
    cpp.write_text(harness)
    subprocess.run(["g++", "-std=c++17", "-Wall", "-Werror", str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("PASS: pending 4K/1080p geometry, refresh-only, deferred and idle transitions")
