// SPDX-License-Identifier: Apache-2.0
#include "TouchControl.h"
#include "TouchReportRate.h"

// Soong defines NDEBUG for host builds too; these checks must always execute.
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>
#include <cstdio>
#include <vector>

using namespace sheng::touch;

struct FakeIo final : Io {
    bool on = true;
    bool stable = true;
    bool offAfterOpen = false;
    bool offAfterSelector = false;
    bool failMode = false;
    int state = 1;
    int opens = 0;
    int closes = 0;
    std::vector<unsigned long> requests;
    TouchCommand last;
    bool panelOn() override { return on; }
    int configured() override { return state; }
    bool stableOn(Cancelled cancel, void* context) override {
        return on && stable && (cancel == nullptr || !cancel(context));
    }
    int openTouch() override { ++opens; if (offAfterOpen) on = false; return 10; }
    void closeTouch(int fd) override { assert(fd == 10); ++closes; }
    int command(int fd, unsigned long request, void* data) override {
        assert(fd == 10);
        requests.push_back(request);
        if (request == kSelectPanel0) {
            assert(data == nullptr);
            if (offAfterSelector) on = false;
            return 0;
        }
        assert(request == kTouchCommand);
        last = *static_cast<TouchCommand*>(data);
        return failMode ? -1 : 0;
    }
};

struct FakeRateTransport final : RateTransport {
    int calls = 0;
    bool last = false, fail = false;
    bool setReport(Io&, bool enabled, Cancelled, void*) override {
        ++calls; last = enabled; return !fail;
    }
};

int main() {
    FakeIo sleeping;
    sleeping.on = false;
    assert(apply(sleeping, 1) == Deferred);
    assert(sleeping.opens == 0 && sleeping.requests.empty());

    FakeIo offRace;
    offRace.offAfterOpen = true;
    assert(apply(offRace, 1) == Deferred);
    assert(offRace.requests.empty() && offRace.closes == 1);

    FakeIo selectorRace;
    selectorRace.offAfterSelector = true;
    assert(apply(selectorRace, 1) == Deferred);
    assert(selectorRace.requests == std::vector<unsigned long>{kSelectPanel0});
    assert(selectorRace.closes == 1);

    FakeIo cancelled;
    assert(apply(cancelled, 1, [](void*) { return true; }) == Deferred);
    assert(cancelled.opens == 0 && cancelled.requests.empty());

    FakeIo awake;
    assert(apply(awake, 1) == Applied);
    assert(awake.requests == (std::vector<unsigned long>{kSelectPanel0, kTouchCommand}));
    assert(awake.closes == 1);
    assert(awake.last.panel == 0 && awake.last.operation == 0);
    assert(awake.last.mode == 14 && awake.last.count == 1 && awake.last.reserved == 0);
    assert(awake.last.data[0] == 1 && awake.last.data[1] == 0);

    FakeIo disabled;
    disabled.state = 0;
    assert(apply(disabled, 0) == Applied && disabled.last.data[0] == 0);

    FakeIo failed;
    failed.failMode = true;
    assert(apply(failed, 1) == Error && failed.closes == 1);
    FakeIo unknown;
    unknown.state = -1;
    assert(apply(unknown, 1) == Unknown);
    FakeIo deferred;
    deferred.state = 0;
    assert(apply(deferred, 1) == Deferred);
    FakeIo invalid;
    assert(apply(invalid, 2) == Invalid && invalid.opens == 0);
    FakeRateTransport report;
    assert(applyReportRate(sleeping, report, 1) == Deferred && report.calls == 0);
    assert(applyReportRate(invalid, report, 2) == Invalid && report.calls == 0);
    assert(applyReportRate(awake, report, 1, [](void*) { return true; }) == Deferred);
    assert(report.calls == 0);
    const auto originalRequests = awake.requests;
    assert(applyReportRate(awake, report, 1) == Applied && report.calls == 1 && report.last);
    assert(applyReportRate(awake, report, 0) == Applied && report.calls == 2 && !report.last);
    assert(awake.requests == originalRequests); // No driver game/gesture commands.
    report.fail = true;
    assert(applyReportRate(awake, report, 1) == Error);
    TouchCommand ack;
    ack.mode = 202; ack.count = 0;
    assert(isReportAcknowledgement(ack));
    ack.mode = 0; assert(!isReportAcknowledgement(ack));
    ack.mode = 14; assert(!isReportAcknowledgement(ack));
    ack.mode = 202; ack.count = 65535; assert(!isReportAcknowledgement(ack));
    ack.count = 0; ack.operation = 1; assert(!isReportAcknowledgement(ack));
    ack.operation = 0; ack.panel = 1; assert(!isReportAcknowledgement(ack));
    puts("PASS OFF/cancellation races, narrow V2 ABI, disable, failure and readback states");
}
