// SPDX-License-Identifier: Apache-2.0
#include "../interfaces/compat/codec2/qti_alac_config.h"

#include <array>
#include <cassert>
#include <cstdio>

using sheng::codec2::convertAlacConfig;

int main() {
    // The generated stereo fixture's ALACSpecificConfig, independent of the
    // production converter: frame length 4096, 16 bits, and 48000 samples/s.
    constexpr std::array<uint8_t, 24> network = {
        0x00, 0x00, 0x10, 0x00, 0x00, 0x10, 0x28, 0x0a,
        0x0e, 0x02, 0x00, 0x00, 0x00, 0x00, 0x40, 0x04,
        0x00, 0x17, 0x70, 0x00, 0x00, 0x00, 0xbb, 0x80,
    };
    constexpr std::array<uint8_t, 24> native = {
        0x00, 0x10, 0x00, 0x00, 0x00, 0x10, 0x28, 0x0a,
        0x0e, 0x02, 0x00, 0x00, 0x04, 0x40, 0x00, 0x00,
        0x00, 0x70, 0x17, 0x00, 0x80, 0xbb, 0x00, 0x00,
    };
    auto source = network;
    std::array<uint8_t, 24> result{};
    assert(convertAlacConfig(source.data(), source.size(), result.data()));
    assert(result == native && source == network);
    result.fill(0x5a);
    const auto sentinel = result;
    assert(!convertAlacConfig(native.data(), native.size(), result.data()));
    assert(result == sentinel);
    assert(!convertAlacConfig(network.data(), 23, result.data()));
    assert(!convertAlacConfig(network.data(), 25, result.data()));
    assert(!convertAlacConfig(nullptr, 24, result.data()));
    assert(!convertAlacConfig(network.data(), 24, nullptr));
    assert(result == sentinel);
    for (size_t offset : {size_t(4), size_t(5), size_t(9), size_t(20)}) {
        source = network;
        source[offset] = 0xff;
        assert(!convertAlacConfig(source.data(), source.size(), result.data()));
        assert(result == sentinel);
    }
    source = network;
    assert(convertAlacConfig(source.data(), source.size(), source.data()));
    assert(source == native);
    // The less frequently used maxRun is also a multibyte field.
    source = network;
    source[10] = 0x12;
    source[11] = 0x34;
    assert(convertAlacConfig(source.data(), source.size(), result.data()));
    assert(result[10] == 0x34 && result[11] == 0x12);
    // Both size and bitrate hints may be unknown in a valid ALAC cookie.
    source = network;
    for (size_t offset = 12; offset < 20; ++offset) source[offset] = 0;
    assert(convertAlacConfig(source.data(), source.size(), result.data()));
    assert(sheng::codec2::alacLittleEndian32(result.data()) == 4096);
    assert(sheng::codec2::alacLittleEndian32(result.data() + 12) >= 16384);
    assert(sheng::codec2::alacLittleEndian32(result.data() + 16) == 1536000);
    assert(result[9] == 2 && result[5] == 16);
    // Reject an unrepresentable fallback without altering the destination.
    for (size_t offset = 0; offset < 4; ++offset) source[offset] = 0xff;
    result = sentinel;
    assert(!convertAlacConfig(source.data(), source.size(), result.data()));
    assert(result == sentinel);
    std::puts("ALAC configuration checks passed");
}
