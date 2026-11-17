#include "PenController.h"
#include "PenHidEndpoint.h"
#include <algorithm>
#include <cerrno>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dirent.h>
#include <fcntl.h>
#include <fstream>
#include <linux/hidraw.h>
#include <linux/input.h>
#include <map>
#include <memory>
#include <string>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>
#include <vector>

using namespace sheng::stylus;

namespace {
unsigned assertions = 0;
void require(bool valid, const char* reason) {
    ++assertions;
    if (!valid) { fprintf(stderr, "FAILED: %s\n", reason); exit(1); }
}
struct Handle {
    std::string kind;
    std::vector<uint8_t> request, reply;
    size_t received = 0;
};
std::map<int, std::shared_ptr<Handle>> handles;
std::vector<uint8_t> descriptor;
std::vector<std::vector<uint8_t>> reports;
std::vector<TouchCommand> wire;
size_t reportIndex = 0;
unsigned directoryIndex = 0;
int nextFd = 50000, product = 0x4d80, vendor = 34;
bool duplicate = false, panelOn = true, failReply = false, badAck = false;
uid_t peerUid = 1000;
double now = 0;
std::string identity = "70:61:EE:8A:6C:67", penName = "Xiaomi Focus Pen";
char directoryToken;
char inputDirectoryToken;
unsigned inputDirectoryIndex = 0;
bool mouseDuplicate = false, wrongMousePeer = false;
std::vector<input_event> mouseEvents;
int allocate(const std::string& kind) {
    const int value = nextFd++;
    handles[value] = std::make_shared<Handle>();
    handles[value]->kind = kind;
    return value;
}
std::vector<uint8_t> unhex(const std::string& hex) {
    require(hex.size() % 2 == 0, "even fixture hexadecimal length");
    std::vector<uint8_t> bytes;
    for (size_t index = 0; index < hex.size(); index += 2)
        bytes.push_back(static_cast<uint8_t>(std::stoul(hex.substr(index, 2), nullptr, 16)));
    return bytes;
}
size_t pressures() {
    return std::count_if(wire.begin(), wire.end(), [](const TouchCommand& command) {
        return command.operation == 7;
    });
}
void mouseBoundaries() {
    const auto savedDescriptor = descriptor;
    product = 0x5081; penName = "Xiaomi Focus Pen Pro";
    descriptor = unhex("05010902a1010901a1008501050919012908150025019508750181020501093009311580257f750895028106"
        "09381580257f750895018106c0c0052009200903a1018506150026ff00750895148102c005010906a1018502"
        "0507194b296e154b256e750895018100c00957a101850515002600407510950409578106150025ff75089506"
        "09578106c0");
    auto endpoint = PenHidEndpoint::openVerified(product, identity);
    require(endpoint && endpoint->setMouseButton(true), "verified Pro mouse primary press");
    require(mouseEvents.size() == 2 && mouseEvents[0].code == BTN_LEFT && mouseEvents[0].value == 1
            && mouseEvents[1].type == EV_SYN, "native primary and sync share actual mouse node");
    require(endpoint->setMouseButton(true) && mouseEvents.size() == 2, "repeated press deduplicated");
    endpoint.reset();
    require(mouseEvents.size() == 4 && mouseEvents[2].value == 0, "owner destruction releases held primary");
    wrongMousePeer = true;
    endpoint = PenHidEndpoint::openVerified(product, identity);
    require(endpoint && !endpoint->setMouseButton(true), "different Bluetooth mouse rejected");
    endpoint.reset(); wrongMousePeer = false; mouseDuplicate = true;
    endpoint = PenHidEndpoint::openVerified(product, identity);
    require(endpoint && !endpoint->setMouseButton(true), "ambiguous mouse endpoints rejected");
    endpoint.reset(); mouseDuplicate = false;
    descriptor = savedDescriptor; product = 0x4d80; penName = "Xiaomi Focus Pen";
    endpoint = PenHidEndpoint::openVerified(product, identity);
    require(endpoint && !endpoint->setMouseButton(true), "ordinary third key does not become Pro mouse click");
    endpoint.reset();
    require(handles.empty(), "mouse endpoint tests close all handles");
}
void identityBoundaries() {
    auto endpoint = PenHidEndpoint::openVerified(product, identity);
    require(endpoint && endpoint->type() == 3 && endpoint->pressureSupported(), "captured ordinary descriptor supported");
    endpoint.reset();
    product = 0x3280;
    require(PenHidEndpoint::openVerified(product, identity) != nullptr, "ordinary alias supported");
    product = 0x4d80;
    require(!PenHidEndpoint::openVerified(product, "00:00:00:00:00:00"), "zero peer rejected");
    require(!PenHidEndpoint::openVerified(product, "70:61:EE:8A:6C:68"), "different peer rejected");
    require(!PenHidEndpoint::openVerified(0x3282, identity), "keyboard product rejected");
    vendor = 35;
    require(!PenHidEndpoint::openVerified(product, identity), "wrong vendor rejected");
    vendor = 34; duplicate = true;
    require(!PenHidEndpoint::openVerified(product, identity), "ambiguous nodes rejected");
    duplicate = false; penName = "Other pen";
    require(!PenHidEndpoint::openVerified(product, identity), "wrong physical name rejected");
    penName = "Xiaomi Focus Pen";
    descriptor.back() ^= 1;
    endpoint = PenHidEndpoint::openVerified(product, identity);
    require(endpoint && !endpoint->pressureSupported(), "unknown ordinary descriptor preserves connection without pressure");
    std::array<uint8_t, 15> report{};
    reports.insert(reports.begin(), std::vector<uint8_t>(15, 5));
    reportIndex = 0;
    const auto unknownRead = endpoint->read(report);
    if (unknownRead != PenHidEndpoint::Read::Other)
        fprintf(stderr, "unknown_read=%d report_index=%zu handles=%zu errno=%d\n",
                static_cast<int>(unknownRead), reportIndex, handles.size(), errno);
    require(unknownRead == PenHidEndpoint::Read::Other, "unknown layout not forwarded");
    reports.erase(reports.begin());
    descriptor.back() ^= 1;
    endpoint.reset();
    require(handles.empty(), "identity probes close every descriptor");
}
void replay() {
    now = 0; panelOn = true; wire.clear(); reportIndex = 0;
    auto hardware = makePosixPenHardware();
    require(!hardware->stableOn(), "real transport applies screen settling");
    now = 2;
    PenController controller(*hardware);
    require(controller.acquire(3) == Result::Applied, "ordinary controller acquires real transport");
    auto endpoint = PenHidEndpoint::openVerified(product, identity);
    require(endpoint && endpoint->pressureSupported(), "replay uses verified native HID endpoint");
    std::array<uint8_t, 15> report{};
    require(controller.forwardPressure(report.data(), report.size()) == Result::Busy, "no pre-ready pressure");
    require(controller.setMode(37, 1) == Result::Applied, "ordinary becomes ready");
    size_t samples = 0;
    while (reportIndex < reports.size()) {
        const auto expected = reports[reportIndex];
        const auto result = endpoint->read(report);
        if (expected[0] != 5) {
            require(result == PenHidEndpoint::Read::Other, "mouse and buttons excluded from pressure");
            continue;
        }
        require(result == PenHidEndpoint::Read::Pressure, "captured pressure accepted by endpoint");
        require(std::equal(expected.begin(), expected.end(), report.begin()), "raw HID bytes remain unchanged");
        require(controller.forwardPressure(report.data(), report.size()) == Result::Applied, "captured sample acknowledged by real THP serializer");
        const auto& sent = wire.back();
        require(sent.panel == 0 && sent.operation == 7 && sent.mode == 1088 && sent.count == 15,
                "stock THP request header retained");
        for (size_t index = 0; index < report.size(); ++index)
            require(sent.data[index] == report[index], "stock byte-per-int32 pressure packing retained");
        require(std::all_of(sent.data.begin() + report.size(), sent.data.end(), [](int32_t value) { return value == 0; }),
                "unused THP data is zeroed");
        ++samples;
    }
    require(samples > 0 && pressures() == samples, "all and only captured pressure frames emitted once");
    require(endpoint->read(report) == PenHidEndpoint::Read::Empty, "EAGAIN is not disconnect");
    report = {5, 1, 0x40};
    require(controller.forwardPressure(report.data(), report.size()) == Result::Invalid && pressures() == samples,
            "overflow pressure never reaches socket");
    report = {5, 0, 0x40};
    require(controller.forwardPressure(report.data(), report.size()) == Result::Applied, "descriptor maximum is not truncated");
    const size_t beforeOff = wire.size();
    panelOn = false; controller.observePanel(false);
    require(controller.forwardPressure(report.data(), report.size()) == Result::Busy, "Off suspends even valid data");
    require(controller.release() == Result::Deferred && wire.size() == beforeOff, "Off cleanup sends nothing");
    panelOn = true; now += 2;
    require(controller.release() == Result::Deferred, "wake still waits for actual display settling");
    now += 2;
    require(controller.release() == Result::Applied, "owned cleanup completes on settled display");
    endpoint.reset(); hardware.reset();
    require(handles.empty(), "replay closes HID, ioctl, panel and socket descriptors");
    printf("captured_pressure_samples=%zu\n", samples);
}
void malformedAndTransportFailures() {
    reports = {{2, 0x4b}, {5, 0, 0}}; reportIndex = 0;
    auto endpoint = PenHidEndpoint::openVerified(product, identity);
    std::array<uint8_t, 15> report{};
    require(endpoint->read(report) == PenHidEndpoint::Read::Other, "short keyboard report ignored");
    require(endpoint->read(report) == PenHidEndpoint::Read::Error, "truncated pressure fails closed");
    endpoint.reset();
    auto hardware = makePosixPenHardware();
    require(!hardware->stableOn(), "new transport settles independently");
    now += 2;
    PenController controller(*hardware);
    require(controller.acquire(3) == Result::Applied && controller.setMode(37, 1) == Result::Applied,
            "failure fixture ready");
    report = {5, 0x34, 0x12};
    failReply = true;
    const size_t before = pressures();
    require(controller.forwardPressure(report.data(), report.size()) == Result::Error,
            "missing ACK is failure, not success");
    require(pressures() == before + 1, "uncertain ACK is not automatically replayed");
    require(controller.release() == Result::Applied, "failed pressure connection releases cleanly");
    require(controller.acquire(3) == Result::Applied && controller.setMode(37, 1) == Result::Applied,
            "new owner may acquire after cleanup");
    badAck = true;
    require(controller.forwardPressure(report.data(), report.size()) == Result::Error,
            "wrong THP ACK rejected");
    require(controller.release() == Result::Applied, "bad ACK owner releases");
    hardware.reset();
    peerUid = 2000;
    hardware = makePosixPenHardware(); hardware->stableOn(); now += 2;
    require(!hardware->pressure(report.data(), report.size()), "wrong THP peer UID rejected");
    peerUid = 1000; hardware.reset();
    require(handles.empty(), "failure paths close all descriptors");
}
}

extern "C" {
int __real_open(const char*, int, ...);
ssize_t __real_read(int, void*, size_t);
int __real_close(int);
DIR* __real_opendir(const char*);
struct dirent* __real_readdir(DIR*);
int __real_closedir(DIR*);

int __wrap_open(const char* path, int flags, ...) {
    if (!strncmp(path, "/dev/input/event", 16)) return allocate("mouse");
    if (!strcmp(path, "/sys/class/drm/card0-DSI-1/dpms")) return allocate("panel");
    if (!strcmp(path, "/dev/xiaomi-touch")) return allocate("touch");
    if (!strncmp(path, "/dev/hidraw", 11)) {
        require((flags & O_NOFOLLOW) && (flags & O_NONBLOCK) && (flags & O_CLOEXEC), "secure nonblocking HID open");
        return allocate("hid");
    }
    if (flags & O_CREAT) {
        va_list arguments; va_start(arguments, flags);
        const mode_t mode = va_arg(arguments, int); va_end(arguments);
        return __real_open(path, flags, mode);
    }
    return __real_open(path, flags);
}
ssize_t __wrap_read(int fd, void* buffer, size_t size) {
    if (!handles.count(fd)) return __real_read(fd, buffer, size);
    if (handles.at(fd)->kind == "panel") {
        const std::string state = panelOn ? "On\n" : "Off\n";
        const size_t count = std::min(size, state.size()); memcpy(buffer, state.data(), count); return count;
    }
    if (reportIndex == reports.size()) { errno = EAGAIN; return -1; }
    const auto& report = reports[reportIndex++];
    const size_t count = std::min(size, report.size()); memcpy(buffer, report.data(), count); return count;
}
ssize_t __wrap___read_chk(int fd, void* buffer, size_t size, size_t capacity) {
    require(size <= capacity, "fortified read stays within buffer");
    return __wrap_read(fd, buffer, size);
}
int __wrap_close(int fd) { return handles.erase(fd) ? 0 : __real_close(fd); }
DIR* __wrap_opendir(const char* path) {
    if (!strcmp(path, "/dev/input")) {
        inputDirectoryIndex = 0; return reinterpret_cast<DIR*>(&inputDirectoryToken);
    }
    if (strcmp(path, "/dev")) return __real_opendir(path);
    directoryIndex = 0; return reinterpret_cast<DIR*>(&directoryToken);
}
struct dirent* __wrap_readdir(DIR* directory) {
    if (directory == reinterpret_cast<DIR*>(&inputDirectoryToken)) {
        if (inputDirectoryIndex >= (mouseDuplicate ? 2u : 1u)) return nullptr;
        static struct dirent inputEntry{};
        snprintf(inputEntry.d_name, sizeof(inputEntry.d_name), "event%u", inputDirectoryIndex++);
        return &inputEntry;
    }
    if (directory != reinterpret_cast<DIR*>(&directoryToken)) return __real_readdir(directory);
    if (directoryIndex >= (duplicate ? 2u : 1u)) return nullptr;
    static struct dirent entry{};
    snprintf(entry.d_name, sizeof(entry.d_name), "hidraw%u", directoryIndex++); return &entry;
}
int __wrap_closedir(DIR* directory) {
    if (directory == reinterpret_cast<DIR*>(&inputDirectoryToken)) return 0;
    return directory == reinterpret_cast<DIR*>(&directoryToken) ? 0 : __real_closedir(directory);
}
int __wrap_ioctl(int fd, unsigned long request, ...) {
    require(handles.count(fd), "ioctl uses owned descriptor");
    va_list arguments; va_start(arguments, request); void* data = va_arg(arguments, void*); va_end(arguments);
    if (handles.at(fd)->kind == "mouse") {
        if (request == EVIOCGID) {
            auto* value = static_cast<input_id*>(data);
            value->bustype = BUS_BLUETOOTH; value->vendor = 34; value->product = product;
        } else if (_IOC_NR(request) == 8 || _IOC_NR(request) == 6) {
            const std::string value = _IOC_NR(request) == 6 ? "Xiaomi Focus Pen Pro Mouse"
                    : wrongMousePeer ? "11:22:33:44:55:66" : identity;
            snprintf(static_cast<char*>(data), _IOC_SIZE(request), "%s", value.c_str());
        } else {
            auto* bits = static_cast<uint8_t*>(data);
            if (_IOC_NR(request) == 0x21) bits[BTN_LEFT / 8] |= 1u << (BTN_LEFT % 8);
            else if (_IOC_NR(request) == 0x22) bits[0] |= (1u << REL_X) | (1u << REL_Y);
            else require(false, "only validated evdev capabilities queried");
        }
    } else if (request == HIDIOCGRAWINFO) {
        auto* info = static_cast<hidraw_devinfo*>(data); info->bustype = 5; info->vendor = vendor; info->product = product;
    } else if (request == HIDIOCGRDESCSIZE) *static_cast<int*>(data) = descriptor.size();
    else if (request == HIDIOCGRDESC) {
        auto* report = static_cast<hidraw_report_descriptor*>(data); memcpy(report->value, descriptor.data(), descriptor.size());
    } else if (_IOC_TYPE(request) == 'H' && (_IOC_NR(request) == 4 || _IOC_NR(request) == 8)) {
        const auto& value = _IOC_NR(request) == 4 ? penName : identity;
        snprintf(static_cast<char*>(data), _IOC_SIZE(request), "%s", value.c_str());
    } else require(request == 0x5403 || request == 0xc2085400, "only expected touch ioctls used");
    return 0;
}
ssize_t __real_write(int, const void*, size_t);
ssize_t __wrap_write(int fd, const void* buffer, size_t length) {
    if (!handles.count(fd)) return __real_write(fd, buffer, length);
    require(handles.at(fd)->kind == "mouse" && length == 2 * sizeof(input_event), "bounded native mouse write");
    const auto* events = static_cast<const input_event*>(buffer);
    mouseEvents.insert(mouseEvents.end(), events, events + 2);
    return length;
}
int __wrap_clock_gettime(clockid_t, struct timespec* value) {
    value->tv_sec = static_cast<time_t>(now); value->tv_nsec = static_cast<long>((now - value->tv_sec) * 1e9); return 0;
}
int __wrap_socket(int domain, int type, int protocol) {
    require(domain == AF_UNIX && (type & SOCK_STREAM) && protocol == 0, "THP stream socket");
    return allocate("socket");
}
int __wrap_setsockopt(int, int level, int option, const void*, socklen_t) {
    require(level == SOL_SOCKET && (option == SO_RCVTIMEO || option == SO_SNDTIMEO), "bounded THP I/O"); return 0;
}
int __wrap_connect(int, const struct sockaddr* address, socklen_t) {
    const auto* local = reinterpret_cast<const sockaddr_un*>(address);
    require(local->sun_family == AF_UNIX && local->sun_path[0] == 0
            && !memcmp(local->sun_path + 1, "thp_socket", 10), "real abstract THP endpoint"); return 0;
}
int __wrap_getsockopt(int, int level, int option, void* value, socklen_t* length) {
    require(level == SOL_SOCKET && option == SO_PEERCRED, "THP peer credentials checked");
    static_cast<ucred*>(value)->uid = peerUid; *length = sizeof(ucred); return 0;
}
int __wrap_fcntl(int fd, int command, ...) {
    require(command == F_DUPFD_CLOEXEC && handles.count(fd), "THP socket copied with close-on-exec");
    const int copy = nextFd++; handles[copy] = handles.at(fd); return copy;
}
ssize_t __wrap_send(int fd, const void* buffer, size_t length, int flags) {
    require(flags == MSG_NOSIGNAL, "THP write cannot terminate process with SIGPIPE");
    auto& handle = *handles.at(fd);
    const size_t count = std::min(length, size_t{73});
    const auto* bytes = static_cast<const uint8_t*>(buffer);
    handle.request.insert(handle.request.end(), bytes, bytes + count);
    if (handle.request.size() == sizeof(TouchCommand)) {
        TouchCommand command; memcpy(&command, handle.request.data(), sizeof(command)); wire.push_back(command);
        command.count = 0;
        if (badAck && command.operation == 7) { command.mode = 0; badAck = false; }
        handle.reply.resize(sizeof(command)); memcpy(handle.reply.data(), &command, sizeof(command)); handle.received = 0;
    }
    require(handle.request.size() <= sizeof(TouchCommand), "bounded stock THP command"); return count;
}
ssize_t __wrap_recv(int fd, void* buffer, size_t length, int) {
    auto& handle = *handles.at(fd);
    if (failReply) { failReply = false; errno = ETIMEDOUT; return -1; }
    require(handle.reply.size() == sizeof(TouchCommand), "read only after complete THP request");
    const size_t count = std::min({length, size_t{101}, handle.reply.size() - handle.received});
    memcpy(buffer, handle.reply.data() + handle.received, count); handle.received += count;
    if (handle.received == handle.reply.size()) { handle.request.clear(); handle.reply.clear(); handle.received = 0; }
    return count;
}
ssize_t __wrap___recv_chk(int fd, void* buffer, size_t length, size_t capacity, int flags) {
    require(length <= capacity, "fortified receive stays within buffer");
    return __wrap_recv(fd, buffer, length, flags);
}
}

int main(int argc, char** argv) {
    require(argc == 3, "descriptor and captured report fixtures required");
    std::ifstream descriptorFile(argv[1], std::ios::binary);
    descriptor.assign(std::istreambuf_iterator<char>(descriptorFile), {});
    require(!descriptor.empty(), "captured descriptor fixture readable");
    std::ifstream reportsFile(argv[2]);
    std::string hex;
    while (reportsFile >> hex) reports.push_back(unhex(hex));
    require(!reports.empty(), "captured reports fixture readable");
    identityBoundaries(); replay(); malformedAndTransportFailures(); mouseBoundaries();
    printf("PASS pressure_pipeline_checks=%u hardware_tested=false transport_peer=host_double\n", assertions);
}
