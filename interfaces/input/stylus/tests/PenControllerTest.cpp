// SPDX-License-Identifier: Apache-2.0
#include "PenController.h"
#include "PenLeaseJournal.h"
#include <csignal>
#include <string>
#include <sys/wait.h>
#include <unistd.h>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <utility>

using namespace sheng::stylus;
namespace {
unsigned assertions = 0;
void require(bool valid, const char* text) {
    ++assertions;
    if (!valid) { fprintf(stderr, "FAILED: %s\n", text); exit(1); }
}
class FakeHardware final : public PenHardware {
  public:
    bool on = true, failNotify = false, failConnect = false, failDisconnect = false;
    bool failReady = false, failPressure = false;
    int failMode = -1;
    int connections = 0, disconnects = 0, pressureWrites = 0;
    std::vector<std::pair<int, int>> modes;
    std::vector<int> notifications;
    bool stableOn() override { return on; }
    bool notifyType(int value) override {
        notifications.push_back(value);
        if (failNotify) { failNotify = false; return false; }
        return true;
    }
    bool setMode(int mode, int value) override {
        modes.emplace_back(mode, value);
        if (mode == failMode) { failMode = -1; return false; }
        if (mode == 37 && failReady) { failReady = false; return false; }
        if (mode == 20) {
            if (value & 16) {
                if (failConnect) { failConnect = false; return false; }
                ++connections;
            } else {
                if (failDisconnect) { failDisconnect = false; return false; }
                ++disconnects; --connections;
                require(connections >= 0, "driver connection count cannot become negative");
            }
        }
        return true;
    }
    bool pressure(const uint8_t*, size_t) override {
        ++pressureWrites;
        return !failPressure;
    }
};

void deathWhileOff() {
    FakeHardware hw;
    PenController pen(hw);
    require(pen.acquire(8) == Result::Applied, "acquire Pro");
    require(pen.setMode(37, 1) == Result::Applied, "ready");
    hw.on = false;
    const size_t commands = hw.modes.size();
    require(pen.release() == Result::Deferred, "client death defers release while Off");
    require(hw.modes.size() == commands, "no Off controller command");
    require(pen.acquire(3) == Result::Busy, "new owner cannot hide unreleased connection");
    require(pen.setMode(37, 1) == Result::Busy, "dead owner cannot write while cleanup pending");
    hw.on = true;
    require(pen.release() == Result::Applied, "wake drains release");
    require(hw.modes[commands] == std::make_pair(37, 0), "ready cleared before disconnect");
    require(hw.connections == 0 && hw.disconnects == 1, "one driver disconnect");
    require(pen.release() == Result::Applied && hw.disconnects == 1, "duplicate death/release is harmless");
    require(pen.acquire(3) == Result::Applied, "ordinary owner may acquire after debt cleared");
    require(pen.release() == Result::Applied, "ordinary owner release");
}

void partialAcquisition(bool notificationFailure) {
    FakeHardware hw;
    hw.failNotify = notificationFailure;
    hw.failConnect = !notificationFailure;
    PenController pen(hw);
    require(pen.acquire(8) == Result::Error, "partial acquisition reports failure");
    require(pen.needsRelease() && !pen.ownsConnection(), "THP debt does not fabricate driver ownership");
    hw.on = false;
    require(pen.release() == Result::Deferred, "partial cleanup respects panel Off");
    hw.on = true;
    require(pen.release() == Result::Applied, "partial type notification reset");
    require(hw.disconnects == 0 && hw.connections == 0, "no decrement after failed connect");
    require(hw.notifications.back() == 8, "THP selector restored");
}

void partialRelease() {
    FakeHardware hw;
    PenController pen(hw);
    require(pen.acquire(8) == Result::Applied && pen.setMode(37, 1) == Result::Applied, "release fixture");
    hw.failDisconnect = true;
    require(pen.release() == Result::Error, "failed ioctl release retained");
    const size_t notifications = hw.notifications.size(), modes = hw.modes.size();
    require(pen.release() == Result::Applied, "retry remaining release");
    require(hw.notifications.size() == notifications, "do not repeat acknowledged THP disconnect");
    require(hw.modes.size() == modes + 1 && hw.modes.back() == std::make_pair(20, 8), "retry only incomplete driver operation");
    require(hw.disconnects == 1 && hw.connections == 0, "retry decrement exactly once");
    require(pen.release() == Result::Applied && hw.disconnects == 1, "no post-cleanup decrement");
}

void pressureBoundaries() {
    FakeHardware hw;
    PenController pen(hw);
    uint8_t report[15]{5, 0xff, 0x3f};
    require(pen.acquire(99) == Result::Invalid && hw.modes.empty(), "unsupported pen rejected");
    require(pen.acquire(3) == Result::Applied && pen.setMode(37, 1) == Result::Applied, "ordinary fixture");
    require(pen.forwardPressure(report, sizeof(report)) == Result::Applied && hw.pressureWrites == 1,
            "descriptor-verified ordinary pressure is forwarded");
    require(pen.setMode(29, 1) == Result::Invalid, "Pro active command excluded from ordinary");
    require(pen.release() == Result::Applied && pen.acquire(8) == Result::Applied, "Pro fixture");
    require(pen.forwardPressure(report, sizeof(report)) == Result::Busy, "no pressure before ready");
    require(pen.setMode(37, 1) == Result::Applied, "Pro ready");
    require(pen.forwardPressure(report, sizeof(report)) == Result::Applied, "16383 pressure retained");
    report[1] = 0; report[2] = 0x40;
    require(pen.forwardPressure(report, sizeof(report)) == Result::Applied, "HID logical maximum retained");
    report[1] = 1;
    require(pen.forwardPressure(report, sizeof(report)) == Result::Invalid, "out-of-range report rejected");
    require(pen.forwardPressure(report, 14) == Result::Invalid, "raw format requires report ID byte");
    report[0] = 2;
    require(pen.forwardPressure(report, sizeof(report)) == Result::Invalid, "keyboard report rejected");
    report[0] = 5; report[1] = 0; report[2] = 0;
    hw.on = false;
    require(pen.forwardPressure(report, sizeof(report)) == Result::Deferred, "no Off pressure write");
    hw.on = true; hw.failPressure = true;
    require(pen.forwardPressure(report, sizeof(report)) == Result::Error && hw.pressureWrites == 4,
            "uncertain pressure ACK is not replayed");
    require(pen.setMode(20, 8) == Result::Invalid, "public setter cannot bypass release ownership");
    require(pen.release() == Result::Applied, "pressure fixture release");
}

void wakeRequiresReady() {
    FakeHardware hw;
    PenController pen(hw);
    uint8_t report[15]{5, 10, 0};
    require(pen.acquire(8) == Result::Applied && pen.setMode(37, 1) == Result::Applied, "wake fixture");
    pen.observePanel(false);
    hw.on = false;
    require(pen.forwardPressure(report, sizeof(report)) == Result::Busy, "observed Off suspends pressure");
    hw.on = true;
    pen.observePanel(true);
    require(pen.forwardPressure(report, sizeof(report)) == Result::Busy && hw.pressureWrites == 0,
            "stable On alone cannot replay pressure before client resumes timing");
    require(pen.setMode(22, 1) == Result::Applied && pen.setMode(22, 259) == Result::Applied,
            "reuse cached two-phase IDs after wake");
    require(pen.forwardPressure(report, sizeof(report)) == Result::Busy, "IDs alone do not enable pressure");
    require(pen.setMode(37, 1) == Result::Applied && pen.forwardPressure(report, sizeof(report)) == Result::Applied,
            "explicit ready resumes pressure");
    require(hw.connections == 1 && hw.disconnects == 0, "wake does not change connection count");
    require(pen.release() == Result::Applied && hw.disconnects == 1, "wake fixture releases once");
}

void transientPanelPause() {
    for (const int type : {3, 8}) {
        FakeHardware hw;
        PenController pen(hw);
        uint8_t report[15]{5, 20, 0};
        require(!pen.needsResume(), "no resume before acquisition");
        require(pen.acquire(type) == Result::Applied && pen.setMode(37, 1) == Result::Applied,
                "transient pause fixture ready");
        require(!pen.needsResume(), "ready panel has no resume debt");
        pen.observePanel(false);
        require(pen.needsResume(), "native-only pause is visible to the client");
        pen.observePanel(true);
        require(pen.needsResume(), "stable On cannot hide pending timing restoration");
        require(pen.forwardPressure(report, sizeof(report)) == Result::Busy,
                "no pressure before explicit resume");
        require(pen.setMode(37, 0) == Result::Applied && !pen.needsResume(),
                "client begins ordered resume without duplicate requests");
        require(pen.setMode(22, 1) == Result::Applied && pen.setMode(22, 259) == Result::Applied,
                "resume restores both timing IDs");
        require(pen.setMode(37, 1) == Result::Applied && !pen.needsResume(), "resume clears native pause");
        require(pen.forwardPressure(report, sizeof(report)) == Result::Applied,
                "pressure resumes after native-only panel pause");
        require(hw.connections == 1 && hw.disconnects == 0, "resume preserves connection ownership");
        require(pen.release() == Result::Applied && !pen.needsResume(), "release clears resume state");
    }
}

void failedModeRequiresRelease() {
    for (const auto& command : std::vector<std::pair<int, int>>{{37, 0}, {37, 1}, {22, 1}, {29, 1}}) {
        FakeHardware hw;
        PenController pen(hw);
        uint8_t report[15]{5, 10, 0};
        require(pen.acquire(8) == Result::Applied && pen.setMode(37, 1) == Result::Applied,
                "failed-mode fixture starts with a ready Pro owner");
        if (command == std::make_pair(37, 1)) {
            require(pen.setMode(37, 0) == Result::Applied, "clear ready before a failed resume");
        }
        hw.failMode = command.first;
        require(pen.setMode(command.first, command.second) == Result::Error,
                "uncertain controller programming returns an error");
        require(pen.forwardPressure(report, sizeof(report)) == Result::Busy && hw.pressureWrites == 0,
                "no pressure may pass between a failed mode and client release");
        require(pen.needsRelease() && hw.connections == 1 && hw.disconnects == 0,
                "a failed mode preserves the exact owned cleanup debt");
        const size_t modes = hw.modes.size();
        require(pen.setMode(37, 1) == Result::Busy && hw.modes.size() == modes,
                "an uncertain owner cannot resume before release");
        hw.on = false;
        require(pen.release() == Result::Deferred && hw.modes.size() == modes,
                "failed-mode cleanup still respects panel Off");
        hw.on = true;
        require(pen.release() == Result::Applied && hw.modes[modes] == std::make_pair(37, 0),
                "cleanup clears attempted ready before the owned disconnect");
        require(hw.connections == 0 && hw.disconnects == 1 && !pen.needsRelease(),
                "failed-mode cleanup finishes one connection");
        require(pen.release() == Result::Applied && hw.disconnects == 1,
                "repeated failed-mode cleanup cannot decrement again");
    }
}

void interruptedServerJournal() {
    char directory[] = "/tmp/sheng-stylus-test-XXXXXX";
    require(mkdtemp(directory) != nullptr, "temporary journal fixture");
    {
        sheng::stylus::PenLeaseJournal first(directory);
        require(!first.blocked() && first.begin(), "commit connection intent before driver writes");
        require(!first.begin(), "same process cannot mark a second connection");
        sheng::stylus::PenLeaseJournal replacement(directory);
        require(replacement.blocked() && !replacement.begin(), "concurrent replacement cannot increment driver");
        require(first.finish(), "acknowledged cleanup removes intent");
    }
    int pipeFds[2];
    require(pipe(pipeFds) == 0, "crash handshake pipe");
    const pid_t child = fork();
    require(child >= 0, "fork journal owner");
    if (child == 0) {
        close(pipeFds[0]);
        sheng::stylus::PenLeaseJournal owner(directory);
        const char result = owner.begin() ? 1 : 0;
        if (write(pipeFds[1], &result, 1) != 1) _exit(2);
        for (;;) pause();
    }
    close(pipeFds[1]);
    char result = 0;
    require(read(pipeFds[0], &result, 1) == 1 && result == 1, "child committed driver intent");
    close(pipeFds[0]);
    require(kill(child, SIGKILL) == 0, "kill actual owning process before cleanup");
    int status = 0;
    require(waitpid(child, &status, 0) == child && WIFSIGNALED(status), "owning process really died");
    {
        sheng::stylus::PenLeaseJournal replacement(directory);
        require(replacement.blocked() && !replacement.begin(), "SIGKILL marker prevents guessed re-acquisition");
        require(!replacement.finish(), "replacement cannot erase another process's ambiguous debt");
    }
    require(unlink((std::string(directory) + "/lease").c_str()) == 0, "remove only fixture marker");
    require(rmdir(directory) == 0, "remove empty temporary fixture");
    sheng::stylus::PenLeaseJournal missing(directory);
    require(missing.blocked() && !missing.begin(), "unavailable journal fails closed");
}
}  // namespace
int main() {
    deathWhileOff(); partialAcquisition(false); partialAcquisition(true);
    partialRelease(); pressureBoundaries(); wakeRequiresReady(); transientPanelPause();
    failedModeRequiresRelease(); interruptedServerJournal();
    printf("PASS assertions=%u: Off death, partial acquire/release, pressure/identity boundaries\n", assertions);
    return 0;
}
