#!/usr/bin/env python3
"""Exercise the actual narrow SCO-release branch with a fake route backend.

This is a host control-flow test, not proof of device/DSP behavior.
"""
from pathlib import Path
import subprocess
import tempfile

source = Path(__file__).resolve().parents[1] / 'interfaces/audio/pal/stream/src/Stream.cpp'
text = source.read_text()
start = text.index('    // A NONE request releases the old SCO route;')
end = text.index('    for (int i = 0; i < mDevices.size(); i++)', start)
branch = text[start:end]
harness = r'''
#include <cassert>
#include <memory>
#include <tuple>
#include <vector>
enum { PAL_DEVICE_NONE, PAL_DEVICE_OUT_BLUETOOTH_SCO, OTHER_DEVICE };
enum { PAL_STREAM_DEEP_BUFFER, OTHER_STREAM };
#define LOG_TAG "test"
#define PAL_INFO(...) ((void)0)
struct Device { int id; int getSndDeviceId() { return id; } };
struct Unlock { bool released=false; void unlock() { released=true; } };
struct Backend {
    bool ready, released=false; int calls=0;
    bool isDeviceReady(int) { return ready; }
    void unlockActiveStream() { released=true; }
    template<class A, class B> int streamDevSwitch(A& a, B& b) {
        assert(released && a.size()==1 && b.empty()); ++calls; return 7;
    }
};
int main() {
    for (int count=0; count<3; ++count)
    for (int request=0; request<3; ++request)
    for (int kind=0; kind<2; ++kind)
    for (int old=1; old<3; ++old)
    for (int ready=0; ready<2; ++ready)
    for (unsigned numDev=0; numDev<3; ++numDev) {
        Backend backend{bool(ready)}; auto rm=&backend;
        Unlock mStreamMutex;
        std::vector<std::shared_ptr<Device>> mDevices;
        for (int i=0; i<count; ++i) mDevices.push_back(std::make_shared<Device>(Device{old}));
        struct {int id;} devices[3]={{request},{request},{request}};
        auto newDevices=devices;
        struct {int type;} strAttr{kind};
        int handle; auto streamHandle=&handle;
        std::vector<std::tuple<int*,int>> streamDevDisconnect, StreamDevConnect;
        int result=[&]() -> int {
BRANCH
            return 99;
        }();
        bool expected=count==1 && request==PAL_DEVICE_NONE && kind==PAL_STREAM_DEEP_BUFFER
            && old==PAL_DEVICE_OUT_BLUETOOTH_SCO && !ready && numDev==1;
        assert((result==7)==expected);
        assert(mStreamMutex.released==expected && backend.released==expected);
        assert(backend.calls==(expected?1:0));
    }
}
'''.replace('BRANCH', branch)
with tempfile.TemporaryDirectory(prefix='sheng-sco-release-') as directory:
    root = Path(directory)
    (root / 'test.cpp').write_text(harness)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    str(root / 'test.cpp'), '-o', str(root / 'test')], check=True)
    subprocess.run([str(root / 'test')], check=True)
print('PASS: 216 actual-branch cases; narrow release, unlock and backend dispatch')
