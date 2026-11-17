// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <array>
#include <cstdint>
#include <memory>
#include <string>

namespace sheng::stylus {
class PenHidEndpoint {
  public:
    enum class Read { Empty, Pressure, Other, Error };
    ~PenHidEndpoint();
    static std::unique_ptr<PenHidEndpoint> openVerified(int product, const std::string& address);
    Read read(std::array<uint8_t, 15>& report);
    int type() const { return type_; }
    bool pressureSupported() const { return pressureSupported_; }
    bool setMouseButton(bool pressed);

  private:
    PenHidEndpoint(int fd, int type, bool supported, int product, const std::string& address)
        : fd_(fd), type_(type), pressureSupported_(supported), product_(product), address_(address) {}
    const int fd_, type_;
    const bool pressureSupported_;
    const int product_;
    const std::string address_;
    int mouseFd_ = -1;
    bool mousePressed_ = false;
};
}  // namespace sheng::stylus
