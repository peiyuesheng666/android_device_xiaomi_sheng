// SPDX-License-Identifier: Apache-2.0
// Diagnostic for the verified stock THP socket ABI. No arbitrary command path.
#include "TouchControl.h"
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <linux/input.h>
#include <poll.h>
#include <signal.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <time.h>

static volatile sig_atomic_t stopping = 0;
static void stopTrial(int) { stopping = 1; }

static double now() {
    timespec value;
    clock_gettime(CLOCK_MONOTONIC, &value);
    return value.tv_sec + value.tv_nsec/1e9;
}

static int exchange(int fd, sheng::touch::TouchCommand& command) {
    const auto request = command;
    size_t sent = 0, received = 0;
    while (sent < sizeof(command)) {
        const ssize_t n = TEMP_FAILURE_RETRY(send(fd, reinterpret_cast<char*>(&command)+sent,
                                                sizeof(command)-sent, MSG_NOSIGNAL));
        if (n <= 0) return -1;
        sent += n;
    }
    while (received < sizeof(command)) {
        const ssize_t n = TEMP_FAILURE_RETRY(recv(fd, reinterpret_cast<char*>(&command)+received,
                                                sizeof(command)-received, 0));
        if (n <= 0) return -1;
        received += n;
    }
    if (command.panel != request.panel || command.operation != request.operation ||
        command.mode != request.mode || command.count == 65535) return -1;
    return 0;
}

static int getGame(int fd) {
    sheng::touch::TouchCommand command;
    command.operation = 1;
    command.mode = 0;
    command.count = 0;
    if (exchange(fd, command) < 0 || command.count != 2) return -1;
    const auto* value = reinterpret_cast<const char*>(command.data);
    if ((value[0] != '0' && value[0] != '1') || value[1] != '\n') return -1;
    return value[0]-'0';
}

static bool setGame(int fd, int value, bool reportOnly = false) {
    sheng::touch::TouchCommand command;
    command.operation = 0;
    command.mode = reportOnly ? 202 : 0;
    command.data[0] = value;
    const double before = now();
    if (exchange(fd, command) < 0) return false;
    const bool matches = getGame(fd) == (reportOnly ? 0 : value);
    if (reportOnly) {
        printf("TRANSITION desired=%d before=%.9f after=%.9f ack=%d daemon_game=%d\n",
               value, before, now(), command.count == 0, getGame(fd));
    } else {
        printf("TRANSITION desired=%d before=%.9f after=%.9f readback=%d\n",
               value, before, now(), matches ? value : -1);
    }
    fflush(stdout);
    return matches;
}

static const char* codeName(const input_event& event) {
    if (event.type == EV_SYN && event.code == SYN_REPORT) return "SYN_REPORT";
    if (event.type == EV_SYN && event.code == SYN_DROPPED) return "SYN_DROPPED";
    if (event.type == EV_ABS && event.code == ABS_MT_SLOT) return "ABS_MT_SLOT";
    if (event.type == EV_ABS && event.code == ABS_MT_TRACKING_ID) return "ABS_MT_TRACKING_ID";
    if (event.type == EV_ABS && event.code == ABS_MT_POSITION_X) return "ABS_MT_POSITION_X";
    if (event.type == EV_ABS && event.code == ABS_MT_POSITION_Y) return "ABS_MT_POSITION_Y";
    return "OTHER";
}

static void logScanState(int phase) {
    for (const char* path : {"/proc/xm_htc_hand_scan_rate", "/proc/xm_htc_op_mode"}) {
        const int fd = open(path, O_RDONLY | O_CLOEXEC);
        if (fd < 0) continue;
        char value[128] = {};
        const ssize_t n = TEMP_FAILURE_RETRY(read(fd, value, sizeof(value)-1));
        char discard[128];
        while (TEMP_FAILURE_RETRY(read(fd, discard, sizeof(discard))) > 0) {}
        close(fd);
        if (n > 0) printf("FIRMWARE phase=%d time=%.9f %s", phase, now(), value);
    }
    fflush(stdout);
}

static int trial(int fd, bool reportOnly) {
    auto io = sheng::touch::makePosixIo();
    if (getGame(fd) != 0) return 3;
    const int input = open("/dev/input/event6", O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    if (input < 0) return 1;
    char name[128] = {};
    if (ioctl(input, EVIOCGNAME(sizeof(name)), name) < 0 ||
        strcmp(name, "NVTCapacitiveTouchScreen")) { close(input); return 1; }
    int clock = CLOCK_MONOTONIC;
    if (ioctl(input, EVIOCSCLOCKID, &clock) < 0) { close(input); return 1; }
    int slot = 0, slots[32];
    for (auto& id : slots) id = -1;
    int phase = 0, reports = 0, dropped = 0;
    bool changed = false, success = false;
    bool sampled[3] = {};
    const double deadline = now()+600;
    double highDeadline = deadline;
    printf("READY thp_socket mode=%d comparison baseline/high/restored; waiting for physical motion\n",
           reportOnly ? 202 : 0);
    fflush(stdout);
    while (!stopping && now() < deadline && now() < highDeadline) {
        if (changed && !io->panelOn()) break;
        pollfd poller = {input, POLLIN, 0};
        if (poll(&poller, 1, 200) < 0) { if (errno == EINTR) continue; break; }
        if (!(poller.revents & POLLIN)) continue;
        input_event events[64];
        const ssize_t n = read(input, events, sizeof(events));
        if (n <= 0) continue;
        for (size_t i = 0; i < static_cast<size_t>(n)/sizeof(input_event); ++i) {
            const auto& e = events[i];
            printf("[ %lld.%06lld] %s %s %08x\n", static_cast<long long>(e.time.tv_sec),
                   static_cast<long long>(e.time.tv_usec),
                   e.type == EV_SYN ? "EV_SYN" : e.type == EV_ABS ? "EV_ABS" : "EV_KEY",
                   codeName(e), e.value);
            if (e.type == EV_ABS && e.code == ABS_MT_SLOT) slot = e.value;
            if (e.type == EV_ABS && e.code == ABS_MT_TRACKING_ID && slot >= 0 && slot < 32)
                slots[slot] = e.value;
            if (e.type == EV_SYN && e.code == SYN_DROPPED) ++dropped;
            if (e.type == EV_SYN && e.code == SYN_REPORT) {
                int active = 0;
                for (auto id : slots) if (id >= 0) ++active;
                if (active == 1) ++reports;
            }
        }
        fflush(stdout);
        if (dropped) break;
        if (!sampled[phase] && reports >= 400) {
            logScanState(phase);
            sampled[phase] = true;
        }
        if (phase == 0 && reports >= 700) {
            if (!io->stableOn(nullptr, nullptr)) break;
            changed = true; // Restore even if the acknowledgement fails.
            if (!setGame(fd, 1, reportOnly)) break;
            phase = 1; reports = 0; highDeadline = now()+30;
        } else if (phase == 1 && reports >= 850) {
            if (!setGame(fd, 0, reportOnly)) break;
            changed = false; phase = 2; reports = 0; highDeadline = deadline;
        } else if (phase == 2 && reports >= 850) { success = true; break; }
    }
    if (changed && !setGame(fd, 0, reportOnly)) { close(input); return 1; }
    close(input);
    printf("FINISHED success=%d restored=%d syn_dropped=%d\n", success, getGame(fd) == 0, dropped);
    return success ? 0 : 1;
}

int main(int argc, char** argv) {
    if (argc != 2 || (strcmp(argv[1], "query") && strcmp(argv[1], "trial") &&
                     strcmp(argv[1], "trial-report"))) return 2;
    signal(SIGPIPE, SIG_IGN);
    signal(SIGTERM, stopTrial);
    signal(SIGINT, stopTrial);
    signal(SIGHUP, stopTrial);
    const int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) return 1;
    timeval timeout = {2, 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    sockaddr_un address = {};
    address.sun_family = AF_UNIX;
    constexpr char name[] = "thp_socket";
    memcpy(address.sun_path+1, name, sizeof(name)-1);
    if (connect(fd, reinterpret_cast<sockaddr*>(&address),
                offsetof(sockaddr_un, sun_path)+sizeof(name)) < 0) {
        perror("connect thp_socket"); close(fd); return 1;
    }
    if (!strcmp(argv[1], "trial") || !strcmp(argv[1], "trial-report")) {
        const int result = trial(fd, !strcmp(argv[1], "trial-report")); close(fd); return result;
    }
    sheng::touch::TouchCommand command;
    command.operation = 1; // Actual daemon's verified user_cmd_get_cur_value.
    command.mode = 0;      // Read-only daemon game/interpolation state.
    command.count = 0;
    const int result = exchange(fd, command);
    close(fd);
    if (result < 0) { perror("query thp_socket"); return 1; }
    printf("thp_socket_mode=0 reply_count=%u reply_bytes=", command.count);
    for (unsigned i = 0; i < 12; ++i) printf("%02x", reinterpret_cast<unsigned char*>(command.data)[i]);
    printf("\n");
    return 0;
}
