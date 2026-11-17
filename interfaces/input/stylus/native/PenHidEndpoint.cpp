// SPDX-License-Identifier: Apache-2.0
#include "PenHidEndpoint.h"
#include <algorithm>
#include <cerrno>
#include <cctype>
#include <cstring>
#include <dirent.h>
#include <fcntl.h>
#include <linux/hidraw.h>
#include <linux/input.h>
#include <sys/ioctl.h>
#include <unistd.h>

// The ROM's glibc 2.17 host sysroot predates this Linux hidraw request.
// Match bionic's UAPI value while retaining the native header on Android.
#ifndef HIDIOCGRAWUNIQ
#define HIDIOCGRAWUNIQ(len) _IOC(_IOC_READ, 'H', 0x08, len)
#endif

namespace sheng::stylus {
namespace {
// Actual Pro descriptor read back in the successful 2026-11-14 trial. The
// vendor report uses fourteen payload bytes; no ordinary layout is inferred.
constexpr char kProDescriptor[] =
    "05010902a1010901a1008501050919012908150025019508750181020501093009311580257f750895028106"
    "09381580257f750895018106c0c0052009200903a1018506150026ff00750895148102c005010906a1018502"
    "0507194b296e154b256e750895018100c00957a101850515002600407510950409578106150025ff75089506"
    "09578106c0";
constexpr char kFocusDescriptor[] =
    "05010902a1010901a1008501050919012908150025019508750181020501093009311580257f750895028106"
    "09381580257f750895018106c0c005010906a10185020507194b296e154b256e750895018100c00957a10185"
    "0515002600407510950409578106150025ff7508950609578106c0";
bool verifiedLayout(int fd, int type) {
    const char* expected = type == 8 ? kProDescriptor : kFocusDescriptor;
    int size = 0;
    if (ioctl(fd, HIDIOCGRDESCSIZE, &size) < 0 || size < 0
            || static_cast<size_t>(size) != strlen(expected) / 2) return false;
    hidraw_report_descriptor descriptor{};
    descriptor.size = static_cast<uint32_t>(size);
    if (ioctl(fd, HIDIOCGRDESC, &descriptor) < 0) return false;
    constexpr char hex[] = "0123456789abcdef";
    for (int i = 0; i < size; ++i) {
        if (expected[2 * i] != hex[descriptor.value[i] >> 4]
                || expected[2 * i + 1] != hex[descriptor.value[i] & 15]) return false;
    }
    return true;
}
bool validAddress(const std::string& address) {
    if (address.size() != 17 || address == "00:00:00:00:00:00" || address == "02:00:00:00:00:00") return false;
    for (size_t i = 0; i < address.size(); ++i) {
        if (i % 3 == 2 ? address[i] != ':' : !std::isxdigit(static_cast<unsigned char>(address[i]))) return false;
    }
    return true;
}
int penType(int product) {
    switch (product) {
        case 0x4d80: case 0x3280: return 3;
        case 0x5081: case 0x3281: return 8;
        default: return 0;
    }
}
}  // namespace
PenHidEndpoint::~PenHidEndpoint() {
    setMouseButton(false);
    if (mouseFd_ >= 0) close(mouseFd_);
    close(fd_);
}

bool PenHidEndpoint::setMouseButton(bool pressed) {
    if (!pressed && !mousePressed_) return true;
    if (type_ != 8 || !pressureSupported_) return false;
    if (mouseFd_ < 0 && pressed) {
        DIR* directory = opendir("/dev/input");
        if (!directory) return false;
        bool ambiguous = false;
        while (dirent* entry = readdir(directory)) {
            const std::string name(entry->d_name);
            if (name.size() <= 5 || name.compare(0, 5, "event") != 0
                    || !std::all_of(name.begin() + 5, name.end(), [](unsigned char value) { return std::isdigit(value); })) continue;
            const int fd = open(("/dev/input/" + name).c_str(), O_RDWR | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC);
            if (fd < 0) continue;
            input_id identity{};
            char unique[128]{}, inputName[128]{};
            uint8_t keys[(KEY_MAX + 8) / 8]{}, relative[(REL_MAX + 8) / 8]{};
            const bool matches = ioctl(fd, EVIOCGID, &identity) >= 0
                    && identity.bustype == BUS_BLUETOOTH && identity.vendor == 34 && identity.product == product_
                    && ioctl(fd, EVIOCGUNIQ(sizeof(unique) - 1), unique) >= 0
                    && strcasecmp(unique, address_.c_str()) == 0
                    && ioctl(fd, EVIOCGNAME(sizeof(inputName) - 1), inputName) >= 0
                    && !strcmp(inputName, "Xiaomi Focus Pen Pro Mouse")
                    && ioctl(fd, EVIOCGBIT(EV_KEY, sizeof(keys)), keys) >= 0
                    && (keys[BTN_LEFT / 8] & (1u << (BTN_LEFT % 8)))
                    && ioctl(fd, EVIOCGBIT(EV_REL, sizeof(relative)), relative) >= 0
                    && (relative[REL_X / 8] & (1u << (REL_X % 8)))
                    && (relative[REL_Y / 8] & (1u << (REL_Y % 8)));
            if (!matches) { close(fd); continue; }
            if (mouseFd_ >= 0) { close(fd); ambiguous = true; break; }
            mouseFd_ = fd;
        }
        closedir(directory);
        if (ambiguous) { close(mouseFd_); mouseFd_ = -1; }
    }
    if (mouseFd_ < 0) return false;
    if (mousePressed_ == pressed) return true;
    input_event events[2]{};
    events[0].type = EV_KEY; events[0].code = BTN_LEFT; events[0].value = pressed ? 1 : 0;
    events[1].type = EV_SYN; events[1].code = SYN_REPORT;
    mousePressed_ = true;
    const ssize_t count = write(mouseFd_, events, sizeof(events));
    if (count != static_cast<ssize_t>(sizeof(events))) return false;
    mousePressed_ = pressed;
    return true;
}

std::unique_ptr<PenHidEndpoint> PenHidEndpoint::openVerified(int product, const std::string& address) {
    const int type = penType(product);
    if (type == 0 || !validAddress(address)) return nullptr;
    DIR* directory = opendir("/dev");
    if (!directory) return nullptr;
    std::unique_ptr<PenHidEndpoint> result;
    while (dirent* entry = readdir(directory)) {
        const std::string name(entry->d_name);
        if (name.size() <= 6 || name.compare(0, 6, "hidraw") != 0
                || !std::all_of(name.begin() + 6, name.end(), [](unsigned char c) { return std::isdigit(c); })) continue;
        const int fd = open(("/dev/" + name).c_str(), O_RDONLY | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC);
        if (fd < 0) continue;
        hidraw_devinfo info{};
        char unique[128]{}, rawName[128]{};
        const bool matches = ioctl(fd, HIDIOCGRAWINFO, &info) >= 0 && info.bustype == 5
                && info.vendor == 34 && info.product == product
                && ioctl(fd, HIDIOCGRAWUNIQ(sizeof(unique) - 1), unique) >= 0
                && strcasecmp(unique, address.c_str()) == 0
                && ioctl(fd, HIDIOCGRAWNAME(sizeof(rawName) - 1), rawName) >= 0
                && !strcmp(rawName, type == 8 ? "Xiaomi Focus Pen Pro" : "Xiaomi Focus Pen");
        if (!matches) { close(fd); continue; }
        const bool pressureSupported = verifiedLayout(fd, type);
        if (type == 8 && !pressureSupported) { close(fd); continue; }
        if (result) { // Ambiguous exact matches must not be chosen by node order.
            close(fd); result.reset(); break;
        }
        result.reset(new PenHidEndpoint(fd, type, pressureSupported, product, address));
    }
    closedir(directory);
    return result;
}

PenHidEndpoint::Read PenHidEndpoint::read(std::array<uint8_t, 15>& report) {
    uint8_t bytes[128]{};
    const ssize_t count = ::read(fd_, bytes, sizeof(bytes));
    if (count < 0 && (errno == EAGAIN || errno == EINTR)) return Read::Empty;
    if (count <= 0) return Read::Error;
    if (!pressureSupported_ || bytes[0] != 5) return Read::Other;
    if (count != 15) return Read::Error;
    std::copy_n(bytes, report.size(), report.begin());
    return Read::Pressure;
}
}  // namespace sheng::stylus
