// SPDX-License-Identifier: Apache-2.0
#include "TouchControl.h"

#include <cstdio>
#include <cstring>

int main(int argc, char** argv) {
    auto io = sheng::touch::makePosixIo();
    if (argc == 2 && !strcmp(argv[1], "--check")) {
        const int configured = io->configured();
        printf("abi=touchfeature_v2 size=520 mode=14 panel_on=%d configured=%d hardware=unverified\n",
               io->panelOn(), configured);
        return configured < 0 ? sheng::touch::Unknown : sheng::touch::Applied;
    }
    if (argc != 3 || strcmp(argv[1], "--set") ||
        (strcmp(argv[2], "0") && strcmp(argv[2], "1"))) {
        fprintf(stderr, "Usage: %s --check | --set <0|1>\n", argv[0]);
        return sheng::touch::Invalid;
    }
    const int desired = argv[2][0] - '0';
    const auto result = sheng::touch::apply(*io, desired);
    printf("mode=14 desired=%d result=%d hardware=unverified\n", desired, result);
    return result;
}
