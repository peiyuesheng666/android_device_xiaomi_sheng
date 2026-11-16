// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>

namespace sheng::touch {

constexpr unsigned long kSelectPanel0 = 0x5403;
constexpr unsigned long kTouchCommand = 0xc2085400;
constexpr uint16_t kDoubleTapMode = 14;

// The supplied stock touchfeature_v2 ABI, not the newer upstream Xiaomi ABI.
struct TouchCommand {
    uint8_t panel = 0;
    uint8_t operation = 0;
    uint16_t mode = kDoubleTapMode;
    uint16_t count = 1;
    uint16_t reserved = 0;
    int32_t data[128] = {};
};
static_assert(sizeof(TouchCommand) == 520);
static_assert(offsetof(TouchCommand, panel) == 0);
static_assert(offsetof(TouchCommand, operation) == 1);
static_assert(offsetof(TouchCommand, mode) == 2);
static_assert(offsetof(TouchCommand, count) == 4);
static_assert(offsetof(TouchCommand, reserved) == 6);
static_assert(offsetof(TouchCommand, data) == 8);

enum Result : int { Applied = 0, Error = 1, Invalid = 2, Deferred = 3, Unknown = 4 };
using Cancelled = bool (*)(void*);

class Io {
  public:
    virtual ~Io() = default;
    virtual bool panelOn() = 0;
    virtual int configured() = 0;
    virtual bool stableOn(Cancelled cancelled, void* context) = 0;
    virtual int openTouch() = 0;
    virtual int command(int fd, unsigned long request, void* data) = 0;
    virtual void closeTouch(int fd) = 0;
};

std::unique_ptr<Io> makePosixIo();
Result apply(Io& io, int desired, Cancelled cancelled = nullptr, void* context = nullptr);

}  // namespace sheng::touch
