// SPDX-License-Identifier: Apache-2.0
// Bounded diagnostic for the stock sheng nanodev ABI. No firmware/reset commands.
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static double now(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

static void *receive(void *arg) {
    int fd = *(int *)arg;
    for (;;) {
        uint8_t reply[256];
        ssize_t n = read(fd, reply, sizeof(reply));
        if (n > 0) {
            if (n > 4 && reply[4] == 0x64) continue; // Repetitive gravity samples.
            // Never print accessory identity, authentication keys or tokens.
            printf("%.3f rx bytes=%zd report=%02x protocol=%02x source=%02x target=%02x cmd=%02x length=%u",
                   now(), n, reply[0], n > 1 ? reply[1] : 0,
                   n > 2 ? reply[2] : 0, n > 3 ? reply[3] : 0,
                   n > 4 ? reply[4] : 0, n > 5 ? reply[5] : 0);
            if (n > 6 && (reply[4] == 0x24 || reply[4] == 0x25 || reply[4] == 0x28))
                printf(" value=%u", reply[6]);
            puts("");
        } else if (n < 0 && errno != EAGAIN && errno != EINTR) {
            printf("read error=%d\n", errno);
            return NULL;
        }
        // The stock driver has no useful poll implementation.
        if (n <= 0) usleep(10000);
    }
}

static int send_command(int fd, int wake) {
    // The OEM HAL removes AA,42 from its 68-byte envelope before write(66).
    uint8_t packet[66] = {0x32, 0, 0x4e, wake ? 0x31 : 0x30,
                          0x80, 0x38, wake ? 0x25 : 0x01, 1,
                          wake ? 1 : 0};
    for (int i = 2; i < 9; ++i) packet[9] += packet[i];
    ssize_t n = write(fd, packet, sizeof(packet));
    printf("%.3f tx %s bytes=%zd errno=%d\n", now(),
           wake ? "power-on" : "version-query", n, n < 0 ? errno : 0);
    return n == sizeof(packet) ? 0 : 1;
}

static int active(void) {
    char panel[16] = {0}, state[512] = {0};
    FILE *file = fopen("/sys/class/drm/card0-DSI-1/dpms", "r");
    if (!file) return 0;
    size_t n = fread(panel, 1, sizeof(panel) - 1, file);
    fclose(file);
    if (!n || (strcmp(panel, "On\n") && strcmp(panel, "On"))) return 0;
    file = fopen("/sys/class/nanodev/nanodev0/_version176x", "r");
    if (!file) return 0;
    n = fread(state, 1, sizeof(state) - 1, file);
    fclose(file);
    return n && strstr(state, "Connected=[1]") && strstr(state, "POGOPIN=[OK]");
}

int main(int argc, char **argv) {
    if (argc != 2 || (strcmp(argv[1], "--query") && strcmp(argv[1], "--wake-trial"))) {
        fprintf(stderr, "Usage: %s --query|--wake-trial\n", argv[0]);
        return 2;
    }
    int wake = !strcmp(argv[1], "--wake-trial");
    setvbuf(stdout, NULL, _IOLBF, 0);
    if (wake && !active()) {
        puts("Waiting up to 180s for display On and attached keyboard; no commands yet");
        for (int i = 0; i < 180 && !active(); ++i) sleep(1);
        if (!active()) { puts("No active keyboard; no commands sent"); return 3; }
    }
    int fd = open("/dev/nanodev0", O_RDWR | O_CLOEXEC | O_NONBLOCK);
    if (fd < 0) { perror("open nanodev"); return 1; }
    pthread_t reader;
    if (pthread_create(&reader, NULL, receive, &fd)) return 1;
    // Observe unsolicited replies before issuing the first request.
    sleep(1);
    int result = send_command(fd, 0);
    sleep(2);
    if (wake && !result) {
        for (int i = 0; i < 4; ++i) {
            if (!active()) { puts("Display off or keyboard detached; trial stopped"); return 3; }
            result |= send_command(fd, 1);
            for (int j = 0; j < 48; ++j) {
                usleep(250000);
                if (!active()) { puts("Display off or keyboard detached; trial stopped"); return 3; }
            }
        }
    }
    sleep(3);
    // Process exit closes both descriptors; no GPIO or persistent state is changed.
    return result;
}
