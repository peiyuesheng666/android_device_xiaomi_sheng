// SPDX-License-Identifier: Apache-2.0
// Temporary bounded display-only probe, credentials dropped before ART seccomp.
#include <grp.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (getuid() != 0 || argc != 2 || strcmp(argv[1], "--120hz")) return 2;
    if (setgroups(0, NULL) || setgid(1000) || setuid(1000)) return 1;
    if (setenv("CLASSPATH", "/data/local/tmp/sheng-pen-display-vote.dex", 1)) return 1;
    execl("/system/bin/app_process", "app_process", "/system/bin",
          "org.lineageos.sheng.diagnostics.ShengPenDisplayVoteProbe", "--120hz", NULL);
    return 1;
}
