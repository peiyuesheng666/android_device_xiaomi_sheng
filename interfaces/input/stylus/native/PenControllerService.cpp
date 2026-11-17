// SPDX-License-Identifier: Apache-2.0
#define LOG_TAG "ShengStylusController"
#include "PenController.h"
#include "PenHidEndpoint.h"
#include "PenLeaseJournal.h"
#include <aidl/vendor/lineage/sheng/stylus/BnPenController.h>
#include <android-base/logging.h>
#include <android/binder_ibinder.h>
#include <android/binder_manager.h>
#include <android/binder_process.h>
#include <chrono>
#include <condition_variable>
#include <csignal>
#include <cstdlib>
#include <mutex>
#include <pthread.h>
#include <thread>

namespace {
using aidl::vendor::lineage::sheng::stylus::BnPenController;
using namespace sheng::stylus;
using ndk::ScopedAStatus;
using ndk::SpAIBinder;

class Service final : public BnPenController {
    struct DeathCookie { std::weak_ptr<Service> service; uint64_t generation; };
    std::mutex mutex_;
    std::condition_variable changed_;
    std::unique_ptr<PenHardware> hardware_ = makePosixPenHardware();
    PenController controller_{*hardware_};
    PenLeaseJournal journal_{"/dev/sheng-stylus"};
    std::unique_ptr<PenHidEndpoint> hid_;
    SpAIBinder owner_;
    AIBinder_DeathRecipient* recipient_;
    DeathCookie* cookie_ = nullptr;
    uint64_t generation_ = 0;
    int64_t forwarded_ = 0;
    bool stopped_ = false;
    bool quiescing_ = false;
    std::chrono::steady_clock::time_point mouseReleaseAt_{};
    std::thread worker_;

    static bool systemCaller() { return AIBinder_getCallingUid() == 1000; }
    Result releaseOwned() {
        const Result result = controller_.release();
        if (!controller_.needsRelease() && !journal_.finish()) {
            LOG(ERROR) << "Connection journal cleanup failed; new acquisition blocked";
            return Result::Error;
        }
        return result;
    }
    bool matches(const SpAIBinder& owner) const {
        return owner.get() && owner_.get() && !AIBinder_lt(owner.get(), owner_.get())
                && !AIBinder_lt(owner_.get(), owner.get());
    }
    void clearOwner() {
        const SpAIBinder previous = owner_;
        DeathCookie* previousCookie = cookie_;
        ++generation_;
        owner_ = SpAIBinder();
        cookie_ = nullptr;
        hid_.reset();
        if (previous.get() && previousCookie) {
            AIBinder_unlinkToDeath(previous.get(), recipient_, previousCookie);
        }
    }
    static void died(void* data) {
        const auto* cookie = static_cast<DeathCookie*>(data);
        const auto self = cookie->service.lock();
        if (!self) return;
        std::lock_guard<std::mutex> lock(self->mutex_);
        if (cookie->generation != self->generation_) return;
        self->clearOwner();
        const Result result = self->releaseOwned();
        LOG(INFO) << "Client died; owned release=" << static_cast<int>(result);
        self->changed_.notify_all();
    }
    void monitor() {
        std::unique_lock<std::mutex> lock(mutex_);
        auto retryAt = std::chrono::steady_clock::time_point{};
        while (!stopped_) {
            // Observe Off even with no pending packet so stable-On includes a
            // full second after every actual wake, not merely after startup.
            const bool on = hardware_->stableOn();
            controller_.observePanel(on);
            if (hid_ && (!on || std::chrono::steady_clock::now() >= mouseReleaseAt_))
                hid_->setMouseButton(false);
            if (!owner_.get() && controller_.needsRelease() && on
                    && std::chrono::steady_clock::now() >= retryAt) {
                const Result result = releaseOwned();
                retryAt = std::chrono::steady_clock::now() + std::chrono::seconds(1);
                LOG(INFO) << "Deferred owned release=" << static_cast<int>(result);
            }
            if (owner_.get() && hid_) {
                for (unsigned i = 0; i < 32; ++i) {
                    std::array<uint8_t, 15> report{};
                    const auto read = hid_->read(report);
                    if (read == PenHidEndpoint::Read::Empty) break;
                    if (read == PenHidEndpoint::Read::Other) continue;
                    if (read == PenHidEndpoint::Read::Error) {
                        clearOwner(); releaseOwned(); break;
                    }
                    const Result result = controller_.forwardPressure(report.data(), report.size());
                    if (result == Result::Applied) {
                        ++forwarded_;
                        if (forwarded_ == 1 || forwarded_ % 512 == 0)
                            LOG(INFO) << "Pressure transport acknowledged count=" << forwarded_;
                    }
                    else if (result == Result::Error || result == Result::Invalid) {
                        LOG(ERROR) << "Pressure transport rejected; releasing owner";
                        clearOwner(); releaseOwned(); break;
                    }
                }
            }
            changed_.wait_for(lock, std::chrono::milliseconds(owner_.get() ? 20 : 200));
        }
    }
  public:
    Service() : recipient_(AIBinder_DeathRecipient_new(died)) {
        AIBinder_DeathRecipient_setOnUnlinked(recipient_, [](void* data) { delete static_cast<DeathCookie*>(data); });
        worker_ = std::thread([this] { monitor(); });
    }
    ~Service() override {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            stopped_ = true;
            clearOwner(); releaseOwned();
        }
        changed_.notify_all();
        worker_.join();
        AIBinder_DeathRecipient_delete(recipient_);
    }
    void beginShutdown() {
        std::lock_guard<std::mutex> lock(mutex_);
        quiescing_ = true;
        clearOwner();
        const Result result = releaseOwned();
        LOG(INFO) << "Service shutdown owned release=" << static_cast<int>(result);
        changed_.notify_all();
    }
    bool shutdownClean() {
        std::lock_guard<std::mutex> lock(mutex_);
        // The same worker drains Off debt on stable On. If init kills us
        // first, the intent marker remains and a replacement fails closed.
        return !controller_.needsRelease() && !journal_.blocked() && journal_.finish();
    }
    ScopedAStatus acquire(const SpAIBinder& owner, int32_t product,
                         const std::string& address, int32_t* result) override {
        if (!systemCaller() || !owner.get()) return ScopedAStatus::fromExceptionCode(EX_SECURITY);
        std::lock_guard<std::mutex> lock(mutex_);
        if (quiescing_) {
            *result = static_cast<int32_t>(Result::Busy); return ScopedAStatus::ok();
        }
        if (journal_.blocked()) {
            LOG(ERROR) << "Interrupted or unavailable driver journal; refusing guessed connection recovery";
            *result = static_cast<int32_t>(Result::Error); return ScopedAStatus::ok();
        }
        if (owner_.get() || controller_.needsRelease()) {
            *result = static_cast<int32_t>(Result::Busy); return ScopedAStatus::ok();
        }
        auto endpoint = PenHidEndpoint::openVerified(product, address);
        if (!endpoint) { *result = static_cast<int32_t>(Result::Invalid); return ScopedAStatus::ok(); }
        owner_ = owner;
        cookie_ = new DeathCookie{ref<Service>(), ++generation_};
        if (AIBinder_linkToDeath(owner.get(), recipient_, cookie_) != STATUS_OK) {
            // onUnlinked also owns cookie deletion on a failed link.
            owner_ = SpAIBinder(); cookie_ = nullptr; ++generation_;
            *result = static_cast<int32_t>(Result::Error); return ScopedAStatus::ok();
        }
        const Result acquired = journal_.begin() ? controller_.acquire(endpoint->type()) : Result::Error;
        *result = static_cast<int32_t>(acquired);
        if (acquired == Result::Applied) {
            LOG(INFO) << "Pressure endpoint type=" << endpoint->type()
                      << " descriptor_verified=" << endpoint->pressureSupported();
            hid_ = std::move(endpoint); forwarded_ = 0;
        }
        else { clearOwner(); if (!controller_.needsRelease()) journal_.finish(); }
        changed_.notify_all();
        return ScopedAStatus::ok();
    }
    ScopedAStatus setMode(const SpAIBinder& owner, int32_t mode,
                         int32_t value, int32_t* result) override {
        if (!systemCaller()) return ScopedAStatus::fromExceptionCode(EX_SECURITY);
        std::lock_guard<std::mutex> lock(mutex_);
        if (mode == 0x10000) {
            const bool allowed = matches(owner) && hid_ && !quiescing_ && (value == 0 || value == 1)
                    && (value == 0 || (controller_.ownsConnection() && !controller_.needsResume() && hardware_->stableOn()));
            const bool applied = allowed && hid_->setMouseButton(value == 1);
            if (applied && value == 1)
                mouseReleaseAt_ = std::chrono::steady_clock::now() + std::chrono::seconds(8);
            LOG(INFO) << "Native mouse primary pressed=" << value << " applied=" << applied;
            *result = static_cast<int32_t>(applied ? Result::Applied : Result::Error);
            return ScopedAStatus::ok();
        }
        *result = static_cast<int32_t>(matches(owner) ? controller_.setMode(mode, value) : Result::Busy);
        return ScopedAStatus::ok();
    }
    ScopedAStatus release(const SpAIBinder& owner, int32_t* result) override {
        if (!systemCaller()) return ScopedAStatus::fromExceptionCode(EX_SECURITY);
        std::lock_guard<std::mutex> lock(mutex_);
        if (!matches(owner)) { *result = static_cast<int32_t>(Result::Busy); return ScopedAStatus::ok(); }
        clearOwner();
        *result = static_cast<int32_t>(releaseOwned());
        changed_.notify_all();
        return ScopedAStatus::ok();
    }
    ScopedAStatus getForwardedCount(const SpAIBinder& owner, int64_t* result) override {
        if (!systemCaller()) return ScopedAStatus::fromExceptionCode(EX_SECURITY);
        std::lock_guard<std::mutex> lock(mutex_);
        *result = !matches(owner) ? -1 : controller_.needsResume() ? -2 : forwarded_;
        return ScopedAStatus::ok();
    }
};
}  // namespace

int main() {
    sigset_t termination;
    sigemptyset(&termination);
    sigaddset(&termination, SIGTERM);
    sigaddset(&termination, SIGINT);
    // Block before creating any thread. sigwait performs cleanup outside a
    // signal handler and serializes with the existing hardware worker.
    CHECK_EQ(pthread_sigmask(SIG_BLOCK, &termination, nullptr), 0);
    ABinderProcess_setThreadPoolMaxThreadCount(2);
    auto service = ndk::SharedRefBase::make<Service>();
    const std::string instance = std::string(Service::descriptor) + "/default";
    CHECK_EQ(AServiceManager_addService(service->asBinder().get(), instance.c_str()), STATUS_OK);
    std::thread([service, termination] {
        int signal = 0;
        if (sigwait(&termination, &signal) != 0) std::_Exit(1);
        LOG(INFO) << "Service termination signal=" << signal;
        service->beginShutdown();
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
        while (!service->shutdownClean() && std::chrono::steady_clock::now() < deadline) {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
        const bool clean = service->shutdownClean();
        LOG(INFO) << "Service termination journal clean=" << clean;
        std::_Exit(clean ? 0 : 1);
    }).detach();
    ABinderProcess_joinThreadPool();
    return 1;
}
