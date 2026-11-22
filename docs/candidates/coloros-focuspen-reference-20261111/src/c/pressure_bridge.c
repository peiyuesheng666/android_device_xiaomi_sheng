/*
 * pressure_bridge.c  v2 —— Focus Pen 压感桥（自适应版）
 *
 * 背景
 *   小米焦点触控笔的压力值由 BLE HID 上报（report ID 5，LE16，上限 8191），
 *   而面板（Novatek）创建的笔输入节点只给 0/1 的“接触/非接触”，没有真实压力。
 *   本程序：抓取面板笔节点 ——> 转发全部事件到 uinput 虚拟笔 ——> 用 HID 的真实压力
 *   替换 ABS_PRESSURE。配合 focuspen_guard 抑制 BT HID 自带的输入节点，避免双份输入。
 *
 * v1 -> v2 的改动（为跨机型移植）
 *   1. 不再写死输入节点名 "NVTCapacitivePen"：
 *      改为「按能力自动识别」（有 EV_ABS + BTN_TOUCH 且无 ABS_MT_SLOT 的事件设备），
 *      并支持 --input 指定/优先匹配。实测 muyu 上真名是 NVTCapacitivePenP81c / NVTCapacitivePenM80p，
 *      sheng 的常量写法在 muyu 上必然匹配失败。
 *   2. 不再写死坐标量程 20319/30479：通过 EVIOCGABS 从源设备读取，虚拟设备镜像之。
 *   3. 不再只声明固定的几个能力位：把源设备 EV_KEY/EV_ABS/EV_MSC 的能力位**整体镜像**到
 *      虚拟设备（内核会丢弃虚拟设备未声明的能力位，v1 会因此丢掉 BTN_DIGI 等事件）。
 *   4. 新增 --probe / --watch：移植前先勘查，打印候选设备、量程、匹配结果。
 *   5. 压力上限自动取源设备 ABS_PRESSURE.max 与 HID 上限的较小者，可用 --pen-max 覆盖。
 *
 * 许可/来源：本工程自研（sheng 侧落地验证），无第三方代码。
 */

#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <linux/uinput.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>
#include "focuspen_identity.h"

#ifndef UI_SET_MSCBIT
#define UI_SET_MSCBIT _IOW(UINPUT_IOCTL_BASE, 104, int)
#endif

#define MAX_CAND 24
#define NAME_LEN 128
#define PATH_LEN 64

static volatile sig_atomic_t running = 1;

static void on_signal(int sig) { (void)sig; running = 0; }

/* ---------------- 基础工具 ---------------- */

static int read_text(const char *path, char *out, size_t cap) {
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    ssize_t n = read(fd, out, cap - 1);
    close(fd);
    if (n <= 0) return -1;
    out[n] = 0;
    /* 只去掉末尾换行；uevent 等多行文件需要保留中间换行 */
    while (n > 0 && (out[n - 1] == '\n' || out[n - 1] == '\r'))
        out[--n] = 0;
    return 0;
}

static bool bit_set(const unsigned long *bits, unsigned idx) {
    return (bits[idx / (8 * sizeof(unsigned long))] >> (idx % (8 * sizeof(unsigned long)))) & 1UL;
}

static bool has_ev(int fd, unsigned type) {
    unsigned long bits[1 + EV_MAX / (8 * sizeof(unsigned long))];
    memset(bits, 0, sizeof(bits));
    if (ioctl(fd, EVIOCGBIT(0, sizeof(bits)), bits) < 0) return false;
    return type <= EV_MAX && bit_set(bits, type);
}

static int abs_max(int fd, unsigned axis) {
    struct input_absinfo info;
    memset(&info, 0, sizeof(info));
    if (ioctl(fd, EVIOCGABS(axis), &info) < 0) return -1;
    return info.maximum;
}

static bool has_key(int fd, unsigned code) {
    unsigned long bits[1 + KEY_MAX / (8 * sizeof(unsigned long))];
    memset(bits, 0, sizeof(bits));
    if (ioctl(fd, EVIOCGBIT(EV_KEY, sizeof(bits)), bits) < 0) return false;
    return code <= KEY_MAX && bit_set(bits, code);
}

static bool has_abs(int fd, unsigned code) {
    unsigned long bits[1 + ABS_MAX / (8 * sizeof(unsigned long))];
    memset(bits, 0, sizeof(bits));
    if (ioctl(fd, EVIOCGBIT(EV_ABS, sizeof(bits)), bits) < 0) return false;
    return code <= ABS_MAX && bit_set(bits, code);
}

/* ---------------- 候选笔输入设备 ---------------- */

struct cand {
    char path[PATH_LEN];   /* /dev/input/eventN */
    char name[NAME_LEN];
    int  max_x, max_y, max_pressure;
    bool matched_name;     /* 命中 --input 候选名 */
};

/* 枚举所有“像笔”的事件设备：有 ABS_X/ABS_Y、有 BTN_TOUCH、但没有 ABS_MT_SLOT（排除触摸屏）。 */
static int scan_candidates(struct cand *out, int cap) {
    DIR *dir = opendir("/sys/class/input");
    if (!dir) return -1;
    struct dirent *e;
    int n = 0;
    while ((e = readdir(dir)) && n < cap) {
        if (strncmp(e->d_name, "event", 5) != 0) continue;
        char p[256];
        snprintf(p, sizeof(p), "/dev/input/%s", e->d_name);
        int fd = open(p, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
        if (fd < 0) continue;
        int mx = abs_max(fd, ABS_X), my = abs_max(fd, ABS_Y);
        int mp = abs_max(fd, ABS_PRESSURE);
        bool ok = has_ev(fd, EV_ABS) && mx > 0 && my > 0
                  && has_key(fd, BTN_TOUCH)
                  && !has_abs(fd, ABS_MT_SLOT);   /* 笔没有 ABS_MT_SLOT，触摸屏才有 */
        if (ok) {
            snprintf(out[n].path, sizeof(out[n].path), "%s", p);
            char np[256];
            snprintf(np, sizeof(np), "/sys/class/input/%s/device/name", e->d_name);
            if (read_text(np, out[n].name, sizeof(out[n].name)) != 0)
                snprintf(out[n].name, sizeof(out[n].name), "(unknown)");
            out[n].max_x = mx;
            out[n].max_y = my;
            out[n].max_pressure = mp;
            out[n].matched_name = false;
            n++;
        }
        close(fd);
    }
    closedir(dir);
    return n;
}

/* 选择源设备：优先命中 --input 候选名；同名多个时优先 pressure 上限与笔 HID 一致者。 */
static int pick_candidate(struct cand *c, int n, const char *name_filter, int pen_max) {
    int best = -1, best_score = -1;
    for (int i = 0; i < n; i++) {
        bool hit = true;
        if (name_filter && *name_filter) {
            hit = false;
            char tmp[1024];
            snprintf(tmp, sizeof(tmp), "%s", name_filter);
            for (char *tok = strtok(tmp, ",|"); tok; tok = strtok(NULL, ",|")) {
                if (strstr(c[i].name, tok)) { hit = true; break; }
            }
        }
        c[i].matched_name = hit;
        if (!hit) continue;
        int score = 0;
        if (pen_max > 0 && c[i].max_pressure == pen_max) score += 100;  /* 量纲一致优先 */
        score += c[i].max_pressure;                                     /* 否则压力上限大者优先 */
        if (score > best_score) { best_score = score; best = i; }
    }
    return best;
}

/* ---------------- 笔 HID（hidraw） ---------------- */

static int find_hidraw(char *path, size_t cap, const char *want_id, const char *want_name) {
    DIR *dir = opendir("/sys/class/hidraw");
    if (!dir) return -1;
    struct dirent *e;
    int found = -1;
    while ((e = readdir(dir))) {
        if (strncmp(e->d_name, "hidraw", 6) != 0) continue;
        char up[256], uevent[1024];
        snprintf(up, sizeof(up), "/sys/class/hidraw/%s/device/uevent", e->d_name);
        if (read_text(up, uevent, sizeof(uevent)) != 0) continue;
        if (focuspen_match_hid(uevent, want_id, want_name)) {
            snprintf(path, cap, "/dev/%s", e->d_name);
            found = 0;
            break;
        }
    }
    closedir(dir);
    return found;
}

/* ---------------- uinput 虚拟笔（镜像源设备能力） ---------------- */

static int create_virtual(int src_fd, int max_pressure, const char *dev_name) {
    int fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) return -1;

    if (ioctl(fd, UI_SET_EVBIT, EV_KEY) < 0 ||
        ioctl(fd, UI_SET_EVBIT, EV_ABS) < 0 ||
        ioctl(fd, UI_SET_EVBIT, EV_MSC) < 0 ||
        ioctl(fd, UI_SET_EVBIT, EV_SYN) < 0) {
        close(fd);
        return -1;
    }

    /* KEY：镜像源设备全部按键能力位 */
    unsigned long kbits[1 + KEY_MAX / (8 * sizeof(unsigned long))];
    memset(kbits, 0, sizeof(kbits));
    if (ioctl(src_fd, EVIOCGBIT(EV_KEY, sizeof(kbits)), kbits) >= 0) {
        for (unsigned c = 0; c <= KEY_MAX; c++)
            if (bit_set(kbits, c)) ioctl(fd, UI_SET_KEYBIT, c);
    }
    /* MSC：镜像 */
    unsigned long mbits[1 + MSC_MAX / (8 * sizeof(unsigned long))];
    memset(mbits, 0, sizeof(mbits));
    if (ioctl(src_fd, EVIOCGBIT(EV_MSC, sizeof(mbits)), mbits) >= 0) {
        for (unsigned c = 0; c <= MSC_MAX; c++)
            if (bit_set(mbits, c)) ioctl(fd, UI_SET_MSCBIT, c);
    }
    /* ABS：镜像源设备全部轴与量程；ABS_PRESSURE 用笔 HID 的上限 */
    unsigned long abits[1 + ABS_MAX / (8 * sizeof(unsigned long))];
    memset(abits, 0, sizeof(abits));
    if (ioctl(src_fd, EVIOCGBIT(EV_ABS, sizeof(abits)), abits) >= 0) {
        for (unsigned c = 0; c <= ABS_MAX; c++) {
            if (!bit_set(abits, c)) continue;
            struct input_absinfo info;
            memset(&info, 0, sizeof(info));
            if (ioctl(src_fd, EVIOCGABS(c), &info) < 0) continue;
            if (c == ABS_PRESSURE && max_pressure > 0) {
                info.maximum = max_pressure;
                if (info.value > info.maximum) info.value = info.maximum;
            }
            struct uinput_abs_setup setup;
            memset(&setup, 0, sizeof(setup));
            setup.code = c;
            setup.absinfo = info;
            if (ioctl(fd, UI_SET_ABSBIT, c) < 0 || ioctl(fd, UI_ABS_SETUP, &setup) < 0) {
                fprintf(stderr, "warn: abs axis %u setup failed\n", c);
            }
        }
    }
    /* 属性位镜像（INPUT_PROP_DIRECT 等） */
    unsigned long pbits[1 + INPUT_PROP_MAX / (8 * sizeof(unsigned long))];
    memset(pbits, 0, sizeof(pbits));
    if (ioctl(src_fd, EVIOCGPROP(sizeof(pbits)), pbits) >= 0) {
        for (unsigned c = 0; c <= INPUT_PROP_MAX; c++)
            if (bit_set(pbits, c)) ioctl(fd, UI_SET_PROPBIT, c);
    }

    struct uinput_setup setup;
    memset(&setup, 0, sizeof(setup));
    setup.id.bustype = BUS_VIRTUAL;
    setup.id.vendor = 0x2717;   /* Xiaomi */
    setup.id.product = 0x6A50;
    setup.id.version = 1;
    snprintf(setup.name, sizeof(setup.name), "%s", dev_name);
    if (ioctl(fd, UI_DEV_SETUP, &setup) < 0 || ioctl(fd, UI_DEV_CREATE) < 0) {
        close(fd);
        return -1;
    }
    return fd;
}

static int send_event(int fd, uint16_t type, uint16_t code, int32_t value) {
    struct input_event ev;
    memset(&ev, 0, sizeof(ev));
    ev.type = type;
    ev.code = code;
    ev.value = value;
    return write(fd, &ev, sizeof(ev)) == (ssize_t)sizeof(ev) ? 0 : -1;
}

/* ---------------- 探测 / 观察 ---------------- */

static void do_probe(const char *name_filter, int pen_max,
                     const char *hid_id, const char *hid_name) {
    printf("== pen input candidates (/dev/input/*, EV_ABS+BTN_TOUCH, no ABS_MT_SLOT) ==\n");
    struct cand c[MAX_CAND];
    int n = scan_candidates(c, MAX_CAND);
    if (n <= 0) printf("  (none)\n");
    for (int i = 0; i < n; i++)
        printf("  [%d] %-20s name=%-24s X<=%-6d Y<=%-6d PRESSURE<=%d\n",
               i, c[i].path, c[i].name, c[i].max_x, c[i].max_y, c[i].max_pressure);
    int pick = pick_candidate(c, n, name_filter, pen_max);
    if (pick >= 0)
        printf("  -> picked [%d] %s (name=%s)  X<=%d Y<=%d\n",
               pick, c[pick].path, c[pick].name, c[pick].max_x, c[pick].max_y);
    else
        printf("  -> NO candidate matched name filter \"%s\"\n", name_filter ? name_filter : "");

    printf("\n== pen HID (hidraw) ==\n");
    char hp[PATH_LEN];
    if (find_hidraw(hp, sizeof(hp), hid_id, hid_name) == 0)
        printf("  found: %s   (id=\"%s\" name=\"%s\")\n", hp, hid_id ? hid_id : "", hid_name ? hid_name : "");
    else
        printf("  NOT found with id=\"%s\" name=\"%s\"\n", hid_id ? hid_id : "", hid_name ? hid_name : "");

    printf("\n== all hidraw uevents (for reference) ==\n");
    DIR *d = opendir("/sys/class/hidraw");
    if (d) {
        struct dirent *e;
        while ((e = readdir(d))) {
            if (strncmp(e->d_name, "hidraw", 6) != 0) continue;
            char up[256], buf[1024];
            snprintf(up, sizeof(up), "/sys/class/hidraw/%s/device/uevent", e->d_name);
            if (read_text(up, buf, sizeof(buf)) == 0) {
                char *line = strtok(buf, "\n");
                printf("  %s:", e->d_name);
                while (line) {
                    if (strncmp(line, "HID_ID", 6) == 0 || strncmp(line, "HID_NAME", 8) == 0)
                        printf(" %s |", line);
                    line = strtok(NULL, "\n");
                }
                printf("\n");
            }
        }
        closedir(d);
    }
    fflush(stdout);
}

/* 观察 N 秒：到底哪个候选节点在真的出事件（用于在 M80p / P81c 之间做选择） */
static void do_watch(int seconds, const char *name_filter) {
    struct cand c[MAX_CAND];
    int n = scan_candidates(c, MAX_CAND);
    int fds[MAX_CAND];
    unsigned frames[MAX_CAND], touches[MAX_CAND];
    for (int i = 0; i < n; i++) {
        fds[i] = -1;
        frames[i] = touches[i] = 0;
        c[i].matched_name = false;
        if (name_filter && *name_filter) {
            char tmp[1024];
            snprintf(tmp, sizeof(tmp), "%s", name_filter);
            for (char *tok = strtok(tmp, ",|"); tok; tok = strtok(NULL, ",|")) {
                if (strstr(c[i].name, tok)) { c[i].matched_name = true; break; }
            }
        }
    }
    for (int i = 0; i < n; i++) fds[i] = open(c[i].path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    printf("watching %d s, 请在屏幕上用笔写几个字…\n", seconds);
    fflush(stdout);
    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    while (running) {
        clock_gettime(CLOCK_MONOTONIC, &t1);
        if (t1.tv_sec - t0.tv_sec >= seconds) break;
        struct pollfd pfds[MAX_CAND];
        for (int i = 0; i < n; i++) { pfds[i].fd = fds[i]; pfds[i].events = POLLIN; pfds[i].revents = 0; }
        if (poll(pfds, n, 500) <= 0) continue;
        for (int i = 0; i < n; i++) {
            if (!(pfds[i].revents & POLLIN)) continue;
            struct input_event ev;
            while (read(fds[i], &ev, sizeof(ev)) == (ssize_t)sizeof(ev)) {
                if (ev.type == EV_SYN && ev.code == SYN_REPORT) frames[i]++;
                if (ev.type == EV_KEY && ev.code == BTN_TOUCH && ev.value) touches[i]++;
            }
        }
    }
    printf("\n结果（%d 秒）：\n", seconds);
    for (int i = 0; i < n; i++) {
        printf("  %-20s %-24s frames=%-7u BTN_TOUCH_DOWN=%-4u %s%s\n",
               c[i].path, c[i].name, frames[i], touches[i],
               touches[i] ? "<== 活动笔节点 " : "",
               c[i].matched_name ? "(命中 --input)" : "");
        if (fds[i] >= 0) close(fds[i]);
    }
    fflush(stdout);
}

/* ---------------- 主循环 ---------------- */

static int run_session(const char *name_filter, const char *hid_id, const char *hid_name,
                       int pen_max_in, const char *virt_name) {
    struct cand c[MAX_CAND];
    int n = scan_candidates(c, MAX_CAND);
    if (n <= 0) return 2;   /* 笔未连接、节点未出现：静默等待，主循环会重试 */
    int pick = pick_candidate(c, n, name_filter, pen_max_in);
    if (pick < 0) { fprintf(stderr, "no candidate matched \"%s\"\n", name_filter); return 2; }

    char hidraw[PATH_LEN];
    if (find_hidraw(hidraw, sizeof(hidraw), hid_id, hid_name) != 0) {
        fprintf(stderr, "pen hidraw not found\n");
        return 2;
    }
    int pen_max = pen_max_in > 0 ? pen_max_in : 8191;
    if (c[pick].max_pressure > 0 && c[pick].max_pressure < pen_max) pen_max = c[pick].max_pressure;

    int input_fd = open(c[pick].path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    int hidraw_fd = open(hidraw, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    if (input_fd < 0 || hidraw_fd < 0) {
        perror("open devices");
        if (input_fd >= 0) close(input_fd);
        if (hidraw_fd >= 0) close(hidraw_fd);
        return 2;
    }
    int virt_fd = create_virtual(input_fd, pen_max, virt_name);
    if (virt_fd < 0) {
        perror("create virtual pen");
        close(input_fd);
        close(hidraw_fd);
        return 2;
    }
    usleep(200000);  /* 让 Android 先把虚拟笔枚举出来，再抓源设备 */
    if (ioctl(input_fd, EVIOCGRAB, 1) < 0) {
        perror("EVIOCGRAB");
        ioctl(virt_fd, UI_DEV_DESTROY);
        close(virt_fd); close(input_fd); close(hidraw_fd);
        return 2;
    }
    fprintf(stderr, "pressure bridge active: %s(%s) + %s  pen_max=%d\n",
            c[pick].path, c[pick].name, hidraw, pen_max);

    bool contact = false;
    int pressure = 0;
    unsigned pressure_changes = 0, pen_frames = 0;

    while (running) {
        struct pollfd fds[2] = {
            { .fd = input_fd, .events = POLLIN },
            { .fd = hidraw_fd, .events = POLLIN }
        };
        int ready = poll(fds, 2, 1000);
        if (ready < 0) { if (errno == EINTR) continue; perror("poll"); break; }

        if (fds[1].revents & POLLIN) {
            uint8_t report[64];
            ssize_t got;
            while ((got = read(hidraw_fd, report, sizeof(report))) > 0) {
                if (got >= 3 && report[0] == 5) {          /* report ID 5 = 压力 */
                    int next = report[1] | (report[2] << 8);
                    if (next > pen_max) next = pen_max;
                    if (next != pressure) {
                        pressure = next;
                        ++pressure_changes;
                        if (contact) {
                            send_event(virt_fd, EV_ABS, ABS_PRESSURE, pressure ? pressure : 1);
                            send_event(virt_fd, EV_SYN, SYN_REPORT, 0);
                        }
                    }
                }
            }
            if (got < 0 && errno != EAGAIN && errno != EWOULDBLOCK) { perror("read HID"); break; }
            if (got == 0) { fprintf(stderr, "HID disconnected\n"); break; }
        }

        if (fds[0].revents & POLLIN) {
            struct input_event ev;
            ssize_t got;
            while ((got = read(input_fd, &ev, sizeof(ev))) == (ssize_t)sizeof(ev)) {
                if (ev.type == EV_KEY && ev.code == BTN_TOUCH) contact = ev.value != 0;
                if (ev.type == EV_ABS && ev.code == ABS_PRESSURE) continue;  /* 丢弃 0/1 假压力 */
                if (ev.type == EV_SYN && ev.code == SYN_REPORT) {
                    send_event(virt_fd, EV_ABS, ABS_PRESSURE,
                               contact ? (pressure ? pressure : 1) : 0);
                    ++pen_frames;
                }
                if (send_event(virt_fd, ev.type, ev.code, ev.value)) {
                    perror("write uinput"); running = 0; break;
                }
            }
            if (got < 0 && errno != EAGAIN && errno != EWOULDBLOCK) { perror("read pen"); break; }
            if (got == 0) { fprintf(stderr, "pen input disconnected\n"); break; }
        }
        if (fds[0].revents & (POLLERR | POLLHUP | POLLNVAL)) break;
        if (fds[1].revents & (POLLERR | POLLHUP | POLLNVAL)) break;
    }

    ioctl(input_fd, EVIOCGRAB, 0);
    ioctl(virt_fd, UI_DEV_DESTROY);
    close(virt_fd); close(input_fd); close(hidraw_fd);
    fprintf(stderr, "pressure bridge stopped: pen_frames=%u pressure_changes=%u\n",
            pen_frames, pressure_changes);
    return 0;
}

static void usage(const char *argv0) {
    fprintf(stderr,
        "usage: %s [options]\n"
        "  --probe                只勘查：列出候选笔输入节点、量程与 hidraw，然后退出\n"
        "  --watch[=SEC]          观察 SEC 秒（默认 8），报告哪个候选节点真的在出事件\n"
        "  --input=NAME[,NAME]    优先匹配的输入节点名（子串），默认 NVTCapacitivePen\n"
        "  --hid-name=NAME        自定义 HID 名称过滤；默认以已知蓝牙 VID/PID 识别，兼容通用名\n"
        "  --hid-id=ID            uevent 中的 HID_ID，默认自动识别 4D80/5081；空串=只按名字\n"
        "  --pen-max=N            压力上限，默认自动（源设备 ABS_PRESSURE.max 与 8191 取小）\n"
        "  --virt-name=NAME       虚拟设备名，默认 \"Xiaomi Focus Pen Pressure\"\n"
        "  --help\n", argv0);
}

int main(int argc, char **argv) {
    const char *name_filter = "NVTCapacitivePen";
    const char *hid_id = NULL;
    const char *hid_name = "HID_NAME=Xiaomi Focus Pen";
    const char *virt_name = "Xiaomi Focus Pen Pressure";
    int pen_max = 0, watch = 0;
    bool probe = false;

    for (int i = 1; i < argc; i++) {
        char *a = argv[i];
        if (!strcmp(a, "--help") || !strcmp(a, "-h")) { usage(argv[0]); return 0; }
        else if (!strcmp(a, "--probe")) probe = true;
        else if (!strncmp(a, "--watch", 7)) { watch = (a[7] == '=') ? atoi(a + 8) : 8; }
        else if (!strncmp(a, "--input=", 8)) name_filter = a + 8;
        else if (!strncmp(a, "--hid-id=", 9)) hid_id = a + 9;
        else if (!strncmp(a, "--hid-name=", 11)) hid_name = a + 11;
        else if (!strncmp(a, "--pen-max=", 10)) pen_max = atoi(a + 10);
        else if (!strncmp(a, "--virt-name=", 12)) virt_name = a + 12;
        else { fprintf(stderr, "unknown option: %s\n", a); usage(argv[0]); return 2; }
    }

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);

    if (probe) { do_probe(name_filter, pen_max, hid_id, hid_name); return 0; }
    if (watch > 0) { do_watch(watch, name_filter); return 0; }

    while (running) {
        run_session(name_filter, hid_id, hid_name, pen_max, virt_name);
        if (running) sleep(2);
    }
    return 0;
}
