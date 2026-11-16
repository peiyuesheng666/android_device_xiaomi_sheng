// SPDX-License-Identifier: Apache-2.0
#include "PenController.h"
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

namespace sheng::stylus {
namespace {
class Fd {
  public:
    explicit Fd(int fd) : value(fd) {}
    ~Fd() { if (value >= 0) close(value); }
    const int value;
};
double monotonic() {
    timespec time{};
    clock_gettime(CLOCK_MONOTONIC, &time);
    return time.tv_sec + time.tv_nsec / 1e9;
}
bool panelOn() {
    Fd panel(open("/sys/class/drm/card0-DSI-1/dpms", O_RDONLY | O_CLOEXEC));
    if (panel.value < 0) return false;
    char state[16]{};
    const ssize_t count = read(panel.value, state, sizeof(state) - 1);
    return count > 0 && (!strcmp(state, "On\n") || !strcmp(state, "On"));
}

class PosixPenHardware final : public PenHardware {
    double observedOn_ = -1;
    int pressureFd_ = -1;

    static int connectThp() {
        Fd socketFd(socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0));
        if (socketFd.value < 0) return -1;
        const timeval timeout{1, 0};
        if (setsockopt(socketFd.value, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) < 0
                || setsockopt(socketFd.value, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)) < 0) return -1;
        sockaddr_un address{};
        address.sun_family = AF_UNIX;
        constexpr char name[] = "thp_socket";
        memcpy(address.sun_path + 1, name, sizeof(name) - 1);
        if (connect(socketFd.value, reinterpret_cast<sockaddr*>(&address),
                    offsetof(sockaddr_un, sun_path) + sizeof(name)) < 0) return -1;
        ucred peer{};
        socklen_t length = sizeof(peer);
        if (getsockopt(socketFd.value, SOL_SOCKET, SO_PEERCRED, &peer, &length) < 0
                || length != sizeof(peer) || peer.uid != 1000) return -1;
        return fcntl(socketFd.value, F_DUPFD_CLOEXEC, 0);
    }
    static bool exchange(int fd, TouchCommand& command) {
        if (fd < 0 || !panelOn()) return false;
        const double deadline = monotonic() + 3;
        for (const bool sending : {true, false}) {
            size_t done = 0;
            while (done < sizeof(command)) {
                if (monotonic() >= deadline || (sending && !panelOn())) return false;
                const ssize_t n = sending
                        ? send(fd, reinterpret_cast<char*>(&command) + done, sizeof(command) - done, MSG_NOSIGNAL)
                        : recv(fd, reinterpret_cast<char*>(&command) + done, sizeof(command) - done, 0);
                if (n < 0 && errno == EINTR) continue;
                if (n <= 0) return false;
                done += static_cast<size_t>(n);
            }
        }
        return true;
    }
  public:
    ~PosixPenHardware() override { if (pressureFd_ >= 0) close(pressureFd_); }
    bool stableOn() override {
        if (!panelOn()) { observedOn_ = -1; return false; }
        const double current = monotonic();
        if (observedOn_ < 0) observedOn_ = current;
        return current - observedOn_ >= 1;
    }
    bool notifyType(int value) override {
        if (value != 3 && value != 8 && value != 19 && value != 24) return false;
        Fd fd(connectThp());
        TouchCommand command;
        command.mode = 20;
        command.data[0] = value;
        return exchange(fd.value, command) && command.panel == 0 && command.operation == 0
                && command.mode == 20 && (command.count == 0 || command.count == 65535);
    }
    bool setMode(int mode, int value) override {
        if (!panelOn()) return false;
        Fd fd(open("/dev/xiaomi-touch", O_RDWR | O_CLOEXEC));
        if (fd.value < 0 || ioctl(fd.value, 0x5403, nullptr) < 0 || !panelOn()) return false;
        TouchCommand command;
        command.mode = static_cast<uint16_t>(mode);
        command.data[0] = value;
        return ioctl(fd.value, 0xc2085400, &command) >= 0;
    }
    bool pressure(const uint8_t* report, size_t length) override {
        if (!report || length != 15 || report[0] != 5) return false;
        if (pressureFd_ < 0) pressureFd_ = connectThp();
        TouchCommand command;
        command.operation = 7;
        command.mode = 1088;
        command.count = static_cast<uint16_t>(length);
        for (size_t i = 0; i < length; ++i) command.data[i] = report[i];
        const bool applied = exchange(pressureFd_, command) && command.panel == 0
                && command.operation == 7 && command.mode == 1088 && command.count == 0;
        if (!applied && pressureFd_ >= 0) {
            close(pressureFd_); pressureFd_ = -1;
            // Never replay an uncertain packet after a partial write/ACK error.
        }
        return applied;
    }
};
}  // namespace
std::unique_ptr<PenHardware> makePosixPenHardware() { return std::make_unique<PosixPenHardware>(); }
}  // namespace sheng::stylus
