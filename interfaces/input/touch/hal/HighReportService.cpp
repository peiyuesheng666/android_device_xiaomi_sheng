// SPDX-License-Identifier: Apache-2.0
#define LOG_TAG "vendor.lineage.touch-service.sheng"
#include "TouchReportRate.h"
#include <aidl/vendor/lineage/touch/BnHighTouchPollingRate.h>
#include <android-base/logging.h>
#include <android-base/properties.h>
#include <android/binder_manager.h>
#include <android/binder_process.h>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <thread>

using aidl::vendor::lineage::touch::BnHighTouchPollingRate;
using namespace sheng::touch;

class HighReport final : public BnHighTouchPollingRate {
    std::mutex mutex;
    std::condition_variable changed;
    bool stopping = false;
    bool observedOn = false;
    int observedRequest = -1, lastApplied = -1, attempts = 0;
    std::chrono::steady_clock::time_point retryAt{};
    std::thread monitor;

    void restoreAfterWake() {
        auto io = makePosixIo();
        auto transport = makeRateTransport();
        std::unique_lock<std::mutex> lock(mutex);
        while (!stopping) {
            const bool on = io->panelOn();
            const int desired = android::base::GetBoolProperty(kHighReportProperty, false) ? 1 : 0;
            if (!on || !observedOn || desired != observedRequest) {
                lastApplied = -1;
                attempts = 0;
                retryAt = {};
            }
            observedOn = on;
            observedRequest = desired;
            if (on && lastApplied != desired && attempts < 5 &&
                std::chrono::steady_clock::now() >= retryAt) {
                const Result result = applyReportRate(*io, *transport, desired);
                ++attempts;
                if (result == Applied) {
                    lastApplied = desired;
                    LOG(INFO) << "mode=202 report_high=" << desired << "; stock daemon acknowledged";
                } else {
                    retryAt = std::chrono::steady_clock::now()+std::chrono::seconds(1);
                    if (attempts == 5) LOG(ERROR) << "mode=202 wake restore failed: " << result;
                }
            }
            // Observe DPMS only while Off. No controller command is sent until
            // the native backend has observed a full second of stable On.
            changed.wait_for(lock, std::chrono::milliseconds(200), [this] { return stopping; });
        }
    }
  public:
    HighReport() : monitor([this] { restoreAfterWake(); }) {}
    ~HighReport() override {
        {
            std::lock_guard<std::mutex> lock(mutex);
            stopping = true;
        }
        changed.notify_all();
        monitor.join();
    }
    ndk::ScopedAStatus getEnabled(bool* enabled) override {
        std::lock_guard<std::mutex> lock(mutex);
        // Requested state persists across sleep; this vendor HAL reapplies
        // it after a stable wake. A socket acknowledgement is not IC scan rate.
        *enabled = android::base::GetBoolProperty(kHighReportProperty, false);
        return ndk::ScopedAStatus::ok();
    }
    ndk::ScopedAStatus setEnabled(bool enabled) override {
        std::lock_guard<std::mutex> lock(mutex);
        const bool previous = android::base::GetBoolProperty(kHighReportProperty, false);
        auto io = makePosixIo();
        auto transport = makeRateTransport();
        const Result result = applyReportRate(*io, *transport, enabled ? 1 : 0);
        if (result != Applied && result != Deferred) {
            LOG(ERROR) << "THP report command failed: " << result;
            return ndk::ScopedAStatus::fromServiceSpecificError(1);
        }
        if (!android::base::SetProperty(kHighReportProperty, enabled ? "1" : "0")) {
            if (result == Applied) applyReportRate(*io, *transport, previous ? 1 : 0);
            lastApplied = -1;
            return ndk::ScopedAStatus::fromServiceSpecificError(2);
        }
        observedRequest = enabled ? 1 : 0;
        observedOn = io->panelOn();
        lastApplied = result == Applied ? observedRequest : -1;
        attempts = 0;
        retryAt = {};
        if (result == Applied) {
            LOG(INFO) << "mode=202 report_high=" << observedRequest << "; stock daemon acknowledged";
        }
        changed.notify_all();
        return ndk::ScopedAStatus::ok();
    }
};

int main() {
    ABinderProcess_setThreadPoolMaxThreadCount(0);
    auto service = ndk::SharedRefBase::make<HighReport>();
    const std::string instance = std::string(HighReport::descriptor)+"/default";
    CHECK_EQ(AServiceManager_addService(service->asBinder().get(), instance.c_str()), STATUS_OK);
    ABinderProcess_joinThreadPool();
    return 1;
}
