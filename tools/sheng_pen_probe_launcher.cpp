// SPDX-License-Identifier: Apache-2.0
#include <unistd.h>
#include <grp.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>

// A temporary diagnostic launcher. Drop credentials before ART installs seccomp.
int main(int argc, char** argv) {
    if (getuid() != 0 || argc != 3 ||
        (strcmp(argv[1], "--scan") != 0 && strcmp(argv[1], "--pair") != 0)) return 2;
    if (strcmp(argv[1], "--pair") == 0) {
        char raw[64] = {};
        FILE* file = fopen("/sys/class/qcom-battery/pen_mac", "r");
        if (!file || !fgets(raw, sizeof(raw), file)) {
            if (file) fclose(file);
            fprintf(stderr, "Charger identity unavailable; leave pen docked\n");
            return 1;
        }
        fclose(file);
        char compact[13] = {};
        int count = 0;
        for (const char* p = argv[2]; *p && count < 12; ++p) if (*p != ':') compact[count++] = *p;
        if (count != 12 || strtoull(raw, nullptr, 16) != strtoull(compact, nullptr, 16)) {
            fprintf(stderr, "Charger identity mismatch\n");
            return 1;
        }
        setenv("SHENG_PEN_VERIFIED_MAC", argv[2], 1);
    }
    if (setgroups(0, nullptr) || setgid(1000) || setuid(1000)) { perror("credentials"); return 1; }
    setenv("CLASSPATH", "/data/local/tmp/sheng-pen-ble-r53.dex", 1);
    execl("/system/bin/app_process", "app_process", "/system/bin",
        "org.lineageos.sheng.diagnostics.ShengPenBleProbe", argv[1], argv[2], nullptr);
    perror("app_process");
    return 1;
}
