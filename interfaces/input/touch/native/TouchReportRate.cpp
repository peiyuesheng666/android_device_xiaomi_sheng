// SPDX-License-Identifier: Apache-2.0
#include "TouchReportRate.h"
#include <cerrno>
#include <cstring>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

namespace sheng::touch {
namespace {
double monotonicSeconds() {
    timespec value;
    clock_gettime(CLOCK_MONOTONIC, &value);
    return value.tv_sec + value.tv_nsec/1e9;
}
class PosixRateTransport final : public RateTransport {
  public:
    bool setReport(Io& io, bool enabled, Cancelled cancelled, void* context) override {
        const int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
        if (fd < 0) return false;
        const bool applied = exchange(fd, io, enabled, cancelled, context);
        close(fd);
        return applied;
    }
  private:
    static bool exchange(int fd, Io& io, bool enabled, Cancelled cancelled, void* context) {
        const double deadline = monotonicSeconds()+3;
        const timeval timeout = {1, 0};
        if (setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) < 0 ||
            setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)) < 0) return false;
        sockaddr_un address = {};
        address.sun_family = AF_UNIX;
        constexpr char name[] = "thp_socket";
        memcpy(address.sun_path+1, name, sizeof(name)-1);
        if (connect(fd, reinterpret_cast<sockaddr*>(&address),
                    offsetof(sockaddr_un, sun_path)+sizeof(name)) < 0) return false;
        ucred peer = {};
        socklen_t peerSize = sizeof(peer);
        if (getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &peer, &peerSize) < 0 ||
            peerSize != sizeof(peer) || peer.uid != 1000) return false;
        TouchCommand command;
        command.mode = kSuperReportMode;
        command.data[0] = enabled ? 1 : 0;
        size_t sent = 0, received = 0;
        while (sent < sizeof(command)) {
            if (monotonicSeconds() >= deadline || !io.panelOn() ||
                (cancelled && cancelled(context))) return false;
            const ssize_t n = TEMP_FAILURE_RETRY(send(fd, reinterpret_cast<char*>(&command)+sent,
                                                    sizeof(command)-sent, MSG_NOSIGNAL));
            if (n <= 0) return false;
            sent += n;
        }
        while (received < sizeof(command)) {
            if (monotonicSeconds() >= deadline || (cancelled && cancelled(context))) return false;
            const ssize_t n = TEMP_FAILURE_RETRY(recv(fd, reinterpret_cast<char*>(&command)+received,
                                                    sizeof(command)-received, 0));
            if (n <= 0) return false;
            received += n;
        }
        // The actual OEM daemon acknowledges setters with count=0. This is an
        // acknowledgement, not a physical-scan readback. Never send mode 0/14 here.
        return isReportAcknowledgement(command);
    }
};
}  // namespace

std::unique_ptr<RateTransport> makeRateTransport() {
    return std::make_unique<PosixRateTransport>();
}

bool isReportAcknowledgement(const TouchCommand& command) {
    return command.panel == 0 && command.operation == 0 &&
           command.mode == kSuperReportMode && command.count == 0;
}

Result applyReportRate(Io& io, RateTransport& transport, int desired,
                       Cancelled cancelled, void* context) {
    if (desired != 0 && desired != 1) return Invalid;
    if (!io.stableOn(cancelled, context)) return Deferred;
    if ((cancelled && cancelled(context)) || !io.panelOn()) return Deferred;
    if (!transport.setReport(io, desired == 1, cancelled, context)) {
        return !io.panelOn() || (cancelled && cancelled(context)) ? Deferred : Error;
    }
    return cancelled && cancelled(context) ? Deferred : Applied;
}
}  // namespace sheng::touch
