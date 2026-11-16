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

  private:
    PenHidEndpoint(int fd, int type, bool supported) : fd_(fd), type_(type), pressureSupported_(supported) {}
    const int fd_, type_;
    const bool pressureSupported_;
};
}  // namespace sheng::stylus
