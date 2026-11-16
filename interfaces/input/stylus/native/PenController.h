// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>

namespace sheng::stylus {
struct TouchCommand {
    uint8_t panel = 0, operation = 0;
    uint16_t mode = 0, count = 1, reserved = 0;
    std::array<int32_t, 128> data{};
};
static_assert(sizeof(TouchCommand) == 520, "sheng stock common_data ABI");

enum class Result { Applied, Deferred, Busy, Invalid, Error };

// The service supplies one instance on its hardware worker. Binder/client death
// calls release; an Off panel leaves debt here until that same worker can retry.
class PenHardware {
  public:
    virtual ~PenHardware() = default;
    virtual bool stableOn() = 0;
    virtual bool notifyType(int value) = 0;
    virtual bool setMode(int mode, int value) = 0;
    virtual bool pressure(const uint8_t* report, size_t length) = 0;
};

class PenController {
  public:
    explicit PenController(PenHardware& hardware) : hardware_(hardware) {}
    Result acquire(int type);
    Result setMode(int mode, int value);
    Result forwardProPressure(const uint8_t* report, size_t length);
    Result release();
    void observePanel(bool stableOn) { if (!stableOn) suspended_ = true; }
    bool ownsConnection() const { return connected_; }
    bool needsRelease() const { return typeNotified_ || connected_ || ready_; }
    bool releasing() const { return releasing_; }
    int type() const { return type_; }

  private:
    PenHardware& hardware_;
    int type_ = 0;
    bool typeNotified_ = false, connected_ = false, ready_ = false;
    bool releasing_ = false, disconnectNotified_ = false;
    bool suspended_ = true;
};

std::unique_ptr<PenHardware> makePosixPenHardware();
}  // namespace sheng::stylus
