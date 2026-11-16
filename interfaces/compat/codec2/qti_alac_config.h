// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace sheng::codec2 {

inline constexpr size_t kAlacConfigSize = 24;

inline uint32_t alacBigEndian32(const uint8_t* value) {
    return (uint32_t(value[0]) << 24) | (uint32_t(value[1]) << 16)
            | (uint32_t(value[2]) << 8) | uint32_t(value[3]);
}

inline uint32_t alacLittleEndian32(const uint8_t* value) {
    return uint32_t(value[0]) | (uint32_t(value[1]) << 8)
            | (uint32_t(value[2]) << 16) | (uint32_t(value[3]) << 24);
}

inline void alacWriteLittleEndian32(uint8_t* target, uint32_t value) {
    for (size_t byte = 0; byte < 4; ++byte) target[byte] = uint8_t(value >> (byte * 8));
}

// Android's MPEG4 extractor supplies an ALACSpecificConfig in network byte
// order. The stock QTI plugins read these fields directly as little endian.
// Recognize that exact format, keeping already-native and unsupported inputs
// intact for the original decoder to handle.
inline bool convertAlacConfig(const uint8_t* source, size_t size, uint8_t* target) {
    if (!source || !target || size != kAlacConfigSize) return false;
    const auto plausibleRate = [](uint32_t rate) { return rate >= 8000 && rate <= 384000; };
    if (!plausibleRate(alacBigEndian32(source + 20))
            || plausibleRate(alacLittleEndian32(source + 20))
            || source[4] != 0 || source[9] == 0 || source[9] > 8
            || (source[5] != 16 && source[5] != 20 && source[5] != 24 && source[5] != 32)
            || alacBigEndian32(source) == 0) {
        return false;
    }
    // The ALAC cookie permits zero packet-size/bitrate hints. QTI rejects a
    // zero packet size, so provide a bounded raw-frame estimate with room for
    // per-channel headers. Neither hint changes the audio samples or framing.
    const uint64_t frameBytes = uint64_t(alacBigEndian32(source)) * source[9]
            * ((source[5] + 7) / 8) + uint64_t(source[9]) * 128;
    const uint64_t bitRate = uint64_t(alacBigEndian32(source + 20)) * source[9] * source[5];
    if (alacBigEndian32(source + 12) == 0 && frameBytes > UINT32_MAX) return false;
    uint8_t converted[kAlacConfigSize];
    std::memcpy(converted, source, sizeof(converted));
    constexpr size_t offsets[] = {0, 12, 16, 20};
    for (size_t offset : offsets) {
        for (size_t byte = 0; byte < 4; ++byte) converted[offset + byte] = source[offset + 3 - byte];
    }
    converted[10] = source[11];
    converted[11] = source[10];
    if (alacBigEndian32(source + 12) == 0) alacWriteLittleEndian32(converted + 12, uint32_t(frameBytes));
    if (alacBigEndian32(source + 16) == 0) alacWriteLittleEndian32(converted + 16, uint32_t(bitRate));
    std::memcpy(target, converted, sizeof(converted));
    return true;
}

}  // namespace sheng::codec2
