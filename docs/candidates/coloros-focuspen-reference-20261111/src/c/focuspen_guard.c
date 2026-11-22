/*
 * focuspen_guard.c —— 抑制小米焦点触控笔自带的 BT HID 输入节点
 *
 * 作用
 *   小米笔通过 BLE HID 呈现为若干输入设备（Pen / Keyboard / Mouse）。
 *   对“笔尖书写”这条链路来说，面板侧另有笔节点在报坐标，若同时还留着
 *   笔的 HID Pen 节点，系统会得到两份输入（重复/抖动）。
 *   本程序把对应 /sys/class/input/<eventN>/inhibited 置 1，从而只保留面板侧坐标。
 *   Pro 使用 BT bus=0005 + VID=0022 + PID=5081 识别并抑制全部 input 子节点；
 *   名称即使回退为 Bluetooth HID / Keyboard / Mouse 也有效，hidraw 仍供压感桥读取。
 *   非 Pro 保持原来的笔本体名称策略，不改变其分离按钮节点。
 *
 * 相对参考包（muyu 原版）的改动 —— 为 Focus Pen Pro 适配
 *   1. 原来的名称匹配会漏过通用 HID 名称，Pro 改为完整硬件 ID 匹配。
 *   2. product 原来只认 "4d80"，现同时接受 Pro 的 "5081"（来源见下表）。
 *   3. 新增 --dry-run / --help，便于在设备上先看再动手。
 *
 * 笔身份表（来自 ROM 内小米 THP 组件的反编译，二者一致才认作笔）：
 *   bus = 0005(BT)，vendor = 0x0022
 *   name "Xiaomi Focus Pen"     + product 0x4d80  → 非 Pro（面板 profile M80p）
 *   name "Xiaomi Focus Pen Pro" + product 0x5081  → Pro   （面板 profile P81c）
 *
 * 编译（aarch64）：
 *   aarch64-linux-android21-clang -O2 -static -o focuspen_guard focuspen_guard.c
 *
 * 许可：本工程自研，无第三方代码。
 */

#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "focuspen_identity.h"

#define MAX_SCAN 512

struct pen_identity {
    const char *name;
    const char *product;   /* /sys/class/input/<event>/device/id/product 的十六进制小写串 */
};

/* 展示型号表；实际匹配采用 BT bus + VID/PID，Pro 的所有输入子节点都需抑制。 */
static const struct pen_identity kPens[] = {
    { "Xiaomi Focus Pen",     "4d80" },   /* 非 Pro */
    { "Xiaomi Focus Pen Pro", "5081" },   /* Pro   */
};
#define PEN_COUNT ((int)(sizeof(kPens) / sizeof(kPens[0])))

static int read_text(const char *path, char *out, size_t size) {
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    ssize_t n = read(fd, out, size - 1);
    close(fd);
    if (n <= 0) return -1;
    out[n] = 0;
    out[strcspn(out, "\r\n")] = 0;   /* 去掉行尾，便于 strcmp */
    return 0;
}

static int suppress_one(const char *event, const char *name, const char *product,
                        int dry_run) {
    char path[512], value[32];

    snprintf(path, sizeof(path), "/sys/class/input/%s/device/inhibited", event);
    if (read_text(path, value, sizeof(value))) {
        fprintf(stderr, "  SKIP %s: 无法读取 inhibited（该节点没有此开关？）\n", event);
        return 1;
    }
    if (dry_run) {
        printf("  WOULD suppress %s  name=\"%s\" product=%s (inhibited 当前=%s)\n",
               event, name, product, value);
        return 0;
    }
    if (strcmp(value, "1") != 0) {
        int fd = open(path, O_WRONLY | O_CLOEXEC);
        if (fd < 0) {
            fprintf(stderr, "  FAIL %s: open O_WRONLY 失败: %s\n", event, strerror(errno));
            return 1;
        }
        ssize_t n = write(fd, "1", 1);
        close(fd);
        if (n != 1) {
            fprintf(stderr, "  FAIL %s: write 失败\n", event);
            return 1;
        }
    }
    if (read_text(path, value, sizeof(value)) || strcmp(value, "1") != 0) {
        fprintf(stderr, "  FAIL %s: 回读校验不通过（inhibited=%s）\n", event, value);
        return 1;
    }
    printf("  suppressed %s  name=\"%s\" vendor=0022 product=%s verified=1\n",
           event, name, product);
    return 0;
}

int main(int argc, char **argv) {
    int dry_run = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--dry-run") || !strcmp(argv[i], "-n")) dry_run = 1;
        else if (!strcmp(argv[i], "--help") || !strcmp(argv[i], "-h")) {
            printf("usage: %s [--dry-run]\n"
                   "  抑制笔的 BT HID 输入（inhibited=1），保留 hidraw 压力读取。\n"
                   "  Pro 按 bus=0005/vendor=0022/product=5081 抑制全部 input 子节点。\n"
                   "  非 Pro 保留名称+硬件 ID 匹配策略；支持型号：\n",
                   argv[0]);
            for (int k = 0; k < PEN_COUNT; k++)
                printf("    \"%s\" + product %s\n", kPens[k].name, kPens[k].product);
            return 0;
        } else {
            fprintf(stderr, "unknown option: %s（用 --help）\n", argv[i]);
            return 2;
        }
    }

    DIR *dir = opendir("/sys/class/input");
    if (!dir) { perror("opendir /sys/class/input"); return 1; }

    struct dirent *entry;
    int matches = 0, failures = 0, visited = 0;
    while ((entry = readdir(dir)) && ++visited <= MAX_SCAN) {
        /* 只看 eventN */
        if (strncmp(entry->d_name, "event", 5) != 0) continue;
        const char *digits = entry->d_name + 5;
        if (!*digits || strspn(digits, "0123456789") != strlen(digits)) continue;

        char path[512], name[128], bus[32], vendor[32], product[32];
        snprintf(path, sizeof(path), "/sys/class/input/%s/device/name", entry->d_name);
        if (read_text(path, name, sizeof(name))) continue;

        snprintf(path, sizeof(path), "/sys/class/input/%s/device/id/bustype", entry->d_name);
        if (read_text(path, bus, sizeof(bus))) continue;
        snprintf(path, sizeof(path), "/sys/class/input/%s/device/id/vendor", entry->d_name);
        if (read_text(path, vendor, sizeof(vendor))) continue;
        snprintf(path, sizeof(path), "/sys/class/input/%s/device/id/product", entry->d_name);
        if (read_text(path, product, sizeof(product))) continue;
        if (!focuspen_suppress_input((unsigned)strtoul(bus, NULL, 16),
                                    (unsigned)strtoul(vendor, NULL, 16),
                                    (unsigned)strtoul(product, NULL, 16), name)) continue;

        ++matches;
        failures += suppress_one(entry->d_name, name, product, dry_run);
    }
    closedir(dir);

    printf("matches=%d failures=%d%s\n", matches, failures,
           matches == 0 ? "  （未发现笔节点：可能未吸附/未连接，或身份表需按实测补充）" : "");
    return failures ? 1 : 0;
}
