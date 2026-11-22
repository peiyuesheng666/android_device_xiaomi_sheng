// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <cmath>
#include <cstdint>

namespace sheng {

// Transform only the discrete runtime event, never metadata/flush payloads
// associated with the orientation sensor. This does not access calibration.
inline float MapDeviceOrientation(bool landscape, int32_t event_type,
                                  int32_t sensor_type, float value) {
    constexpr int32_t kDeviceOrientation = 27;
    if (!landscape || event_type != kDeviceOrientation || sensor_type != kDeviceOrientation ||
        !std::isfinite(value) || value < 0 || value > 3 || std::trunc(value) != value) {
        return value;
    }
    return (static_cast<int>(value) + 3) % 4;
}

}  // namespace sheng
