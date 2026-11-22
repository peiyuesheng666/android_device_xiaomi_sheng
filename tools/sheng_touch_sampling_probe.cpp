// SPDX-License-Identifier: Apache-2.0
// Bounded native trial for the stock mode-0 command, never an arbitrary setter.
#include "TouchControl.h"
#include <cstdio>
#include <cstring>

int main(int argc, char** argv) {
    if (argc != 2 || (strcmp(argv[1], "0") && strcmp(argv[1], "1"))) return 2;
    auto io = sheng::touch::makePosixIo();
    if (!io->stableOn(nullptr, nullptr)) return 3;
    const int fd = io->openTouch();
    if (fd < 0) return 1;
    int result = 3;
    if (io->panelOn() && io->command(fd, sheng::touch::kSelectPanel0, nullptr) >= 0 && io->panelOn()) {
        sheng::touch::TouchCommand command;
        command.mode = 0;  // Verified stock branch and initialized boolean range.
        command.data[0] = argv[1][0] - '0';
        result = io->command(fd, sheng::touch::kTouchCommand, &command) < 0 ? 1 : 0;
    }
    io->closeTouch(fd);
    printf("stock_mode=0 desired=%s ioctl_result=%d sampling_unverified=1\n", argv[1], result);
    return result;
}
