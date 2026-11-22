// SPDX-License-Identifier: Apache-2.0
#include "../aidl/sensors/ShengOrientationSample.h"
#include <cassert>
#include <limits>

int main() {
    for (int i = 0; i < 4; ++i) {
        assert(sheng::MapDeviceOrientation(true, 27, 27, i) == (i + 3) % 4);
        assert(sheng::MapDeviceOrientation(false, 27, 27, i) == i);
        assert(sheng::MapDeviceOrientation(true, 0, 27, i) == i);
        assert(sheng::MapDeviceOrientation(true, 33, 27, i) == i);
        assert(sheng::MapDeviceOrientation(true, 27, 1, i) == i);
    }
    // Metadata union words can alias tiny floats; preserve them exactly.
    float tiny = std::numeric_limits<float>::denorm_min();
    assert(sheng::MapDeviceOrientation(true, 0, 27, tiny) == tiny);
    assert(sheng::MapDeviceOrientation(true, 27, 27, 0.5f) == 0.5f);
    assert(sheng::MapDeviceOrientation(true, 27, 27, -1) == -1);
    assert(sheng::MapDeviceOrientation(true, 27, 27, 4) == 4);
    assert(std::isnan(sheng::MapDeviceOrientation(true, 27, 27,
        std::numeric_limits<float>::quiet_NaN())));
}
