// SPDX-License-Identifier: Apache-2.0
#include "TouchControl.h"

#include <cerrno>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

namespace sheng::touch {
namespace {
constexpr char kPanel[] = "/sys/class/drm/card0-DSI-1/dpms";
constexpr char kConfigured[] = "/proc/xm_htc_gesture_switch";

bool isCancelled(Cancelled cancelled, void* context) {
    return cancelled != nullptr && cancelled(context);
}

class PosixIo final : public Io {
  public:
    bool panelOn() override {
        const int fd = open(kPanel, O_RDONLY | O_CLOEXEC);
        if (fd < 0) return false;
        char value[16] = {};
        const ssize_t n = TEMP_FAILURE_RETRY(read(fd, value, sizeof(value) - 1));
        close(fd);
        return n > 0 && (!strcmp(value, "On\n") || !strcmp(value, "On"));
    }

    int configured() override {
        // The stock proc has a global EOF flag. Drain each open and retry an empty one.
        for (int attempt = 0; attempt < 2; ++attempt) {
            const int fd = open(kConfigured, O_RDONLY | O_CLOEXEC);
            if (fd < 0) return -1;
            char value[128] = {};
            const ssize_t n = TEMP_FAILURE_RETRY(read(fd, value, sizeof(value) - 1));
            if (n < 0) { close(fd); return -1; }
            char discard[128];
            ssize_t tail;
            do { tail = TEMP_FAILURE_RETRY(read(fd, discard, sizeof(discard))); }
            while (tail > 0);
            close(fd);
            if (tail < 0) return -1;
            if (n == 0) continue;
            unsigned flags;
            if (sscanf(value, "gesture_switch: %u", &flags) == 1 && flags <= 3) {
                return flags & 1;  // Bit 1 belongs to the independent pen gesture.
            }
            return -1;
        }
        return -1;
    }

    bool stableOn(Cancelled cancelled, void* context) override {
        // Finite, monotonic settling checks. No timer or polling survives panel OFF.
        for (int step = 0; step <= 10; ++step) {
            if (isCancelled(cancelled, context) || !panelOn()) return false;
            if (step == 10) return true;
            timespec remaining = {0, 100000000};
            while (nanosleep(&remaining, &remaining) < 0) {
                if (errno != EINTR || isCancelled(cancelled, context)) return false;
            }
        }
        return false;
    }

    int openTouch() override { return open("/dev/xiaomi-touch", O_RDWR | O_CLOEXEC); }
    int command(int fd, unsigned long request, void* data) override {
        return ioctl(fd, request, data);
    }
    void closeTouch(int fd) override { close(fd); }
};
}  // namespace

std::unique_ptr<Io> makePosixIo() { return std::make_unique<PosixIo>(); }

Result apply(Io& io, int desired, Cancelled cancelled, void* context) {
    if (desired != 0 && desired != 1) return Invalid;
    if (!io.stableOn(cancelled, context)) return Deferred;
    if (isCancelled(cancelled, context) || !io.panelOn()) return Deferred;
    const int fd = io.openTouch();
    if (fd < 0) return Error;
    // Keep the rechecks adjacent to each ioctl; the kernel also defers mode 14
    // while its IC state is suspending/off/resuming and updates DSI power flags.
    Result result = Deferred;
    if (!isCancelled(cancelled, context) && io.panelOn()) {
        if (io.command(fd, kSelectPanel0, nullptr) < 0) {
            result = Error;
        } else if (!isCancelled(cancelled, context) && io.panelOn()) {
            TouchCommand command;
            command.data[0] = desired;
            result = io.command(fd, kTouchCommand, &command) < 0 ? Error : Applied;
        }
    }
    io.closeTouch(fd);
    if (result != Applied) return result;
    const int configured = io.configured();
    if (configured < 0) return Unknown;
    return configured == desired ? Applied : Deferred;
}
}  // namespace sheng::touch
