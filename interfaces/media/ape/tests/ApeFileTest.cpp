// SPDX-License-Identifier: Apache-2.0
#include "ApeFile.h"

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <limits>

using namespace sheng::ape;

static unsigned checks = 0;
static void check(bool value) {
    ++checks;
    if (!value) {
        std::fprintf(stderr, "APE parser check %u failed\n", checks);
        std::exit(1);
    }
}

class Memory final : public ByteSource {
public:
    std::vector<uint8_t> bytes;
    uint64_t declaredSize = 0;
    uint64_t failAt = UINT64_MAX;
    uint64_t size() const override { return declaredSize ? declaredSize : bytes.size(); }
    bool readAt(uint64_t offset, void* data, size_t count) override {
        check(offset <= size() && count <= size() - offset);
        if (offset >= failAt || offset > bytes.size() || count > bytes.size() - offset) return false;
        std::memcpy(data, bytes.data() + offset, count);
        return true;
    }
};

static Memory fixture() {
    Memory m;
    m.bytes.resize(138);
    auto* b = m.bytes.data();
    std::memcpy(b, "MAC ", 4);
    put16(b + 4, 3990);
    put32(b + 8, 52);
    put32(b + 12, 24);
    put32(b + 16, 12);
    put32(b + 24, 50);
    put16(b + 52, 2000);
    put32(b + 56, 73728);
    put32(b + 60, 12345);
    put32(b + 64, 3);
    put16(b + 68, 16);
    put16(b + 70, 2);
    put32(b + 72, 44100);
    put32(b + 76, 88);
    put32(b + 80, 105);
    put32(b + 84, 126);
    for (size_t i = 88; i < m.bytes.size(); ++i) b[i] = i;
    return m;
}

static void reject32(size_t position, uint32_t value) {
    auto m = fixture();
    put32(m.bytes.data() + position, value);
    ApeFile file;
    check(ApeFile::parse(m, &file) != ParseResult::Ok);
    check(file.frameCount() == 0 && file.maxPacketBytes() == 0);
}

static void reject16(size_t position, uint16_t value) {
    auto m = fixture();
    put16(m.bytes.data() + position, value);
    ApeFile file;
    check(ApeFile::parse(m, &file) != ParseResult::Ok);
    check(file.frameCount() == 0);
}

int main(int argc, char** argv) {
    auto m = fixture();
    ApeFile file;
    check(ApeFile::parse(m, &file) == ParseResult::Ok);
    check(file.frameCount() == 3 && file.sampleCount() == 159801);
    check(file.sampleRate() == 44100 && file.channels() == 2 && file.maxPacketBytes() == 32);
    const uint64_t offsets[] = {88, 104, 124};
    const uint32_t lengths[] = {16, 20, 12};
    const uint32_t skips[] = {0, 1, 2};
    for (uint32_t i = 0; i < 3; ++i) {
        Packet p{};
        check(file.packet(i, &p));
        check(p.offset == offsets[i] && p.payloadBytes == lengths[i] && p.skipBytes == skips[i]);
        std::vector<uint8_t> output(p.size() + 2, 0x5a);
        check(!file.readPacket(m, i, output.data() + 1, p.size() - 1));
        check(file.readPacket(m, i, output.data() + 1, p.size()));
        check(output.front() == 0x5a && output.back() == 0x5a);
        check(le32(output.data() + 1) == lengths[i] && le32(output.data() + 5) == skips[i]);
        check(le32(output.data() + 9) == i);
        check(std::memcmp(output.data() + 13, m.bytes.data() + offsets[i], lengths[i]) == 0);
    }
    Packet p{};
    check(!file.packet(3, &p) && !file.packet(UINT32_MAX, &p) && !file.packet(0, nullptr));
    const auto csd = file.codecConfig();
    check(le16(csd.data()) == 3990 && le16(csd.data() + 2) == 2000);
    check(le32(csd.data() + 8) == 73728 && le32(csd.data() + 12) == 12345);
    check(le32(csd.data() + 16) == 3 && le32(csd.data() + 28) == 1);
    const int64_t first = file.frameTimeUs(1), second = file.frameTimeUs(2);
    for (auto mode : {SeekMode::Previous, SeekMode::Next, SeekMode::Closest}) {
        check(file.seekFrame(-1, mode) == 0);
        check(file.seekFrame(0, mode) == 0);
        check(file.seekFrame(first, mode) == 1);
        check(file.seekFrame(second, mode) == 2);
        check(file.seekFrame(INT64_MAX, mode) == 2);
    }
    check(file.seekFrame(first - 1, SeekMode::Previous) == 0);
    check(file.seekFrame(first - 1, SeekMode::Next) == 1);
    check(file.seekFrame(first + 1, SeekMode::Previous) == 1);
    check(file.seekFrame(first + 1, SeekMode::Next) == 2);
    check(file.seekFrame(first + 1, SeekMode::Closest) == 1);
    check(file.seekFrame(second - 1, SeekMode::Closest) == 2);
    check(file.seekFrame(1, SeekMode::FrameIndex) == 1);
    check(file.seekFrame(INT64_MAX, SeekMode::FrameIndex) == 2);

    for (size_t length = 0; length < m.bytes.size(); ++length) {
        auto truncated = m;
        truncated.bytes.resize(length);
        check(ApeFile::parse(truncated, &file) != ParseResult::Ok);
    }
    for (uint64_t fail : {uint64_t(0), uint64_t(52), uint64_t(76)}) {
        auto broken = m;
        broken.failAt = fail;
        check(ApeFile::parse(broken, &file) == ParseResult::IoError);
    }
    reject16(0, 0);
    for (uint16_t version : {3970, 3991, 65535}) reject16(4, version);
    for (uint32_t offset : {8, 12}) { reject32(offset, 0); reject32(offset, UINT32_MAX); }
    for (uint32_t count : {0u, 4u, 11u, 13u, UINT32_MAX}) reject32(16, count);
    reject32(20, UINT32_MAX);
    for (uint32_t count : {0u, 36u, 51u, UINT32_MAX}) reject32(24, count);
    reject32(28, 1);
    reject32(32, UINT32_MAX);
    reject32(56, 0);
    reject32(56, 294913);
    reject32(60, 0);
    reject32(60, 73729);
    for (uint32_t count : {0u, 4u, ApeFile::kMaxFrames + 1, UINT32_MAX}) reject32(64, count);
    for (uint16_t level : {0, 2001, 4000, 5000}) reject16(52, level);
    reject16(54, 1);
    reject16(68, 24);
    reject16(70, 0);
    reject16(70, 3);
    reject32(72, 7999);
    reject32(72, 192001);
    for (uint32_t offset : {0u, 87u, 89u, 138u, UINT32_MAX}) reject32(76, offset);
    for (uint32_t offset : {87u, 88u, 89u, 138u, UINT32_MAX}) reject32(80, offset);
    for (uint32_t offset : {104u, 105u, 106u, 137u, 138u, UINT32_MAX}) reject32(84, offset);
    auto huge = m;
    huge.declaredSize = uint64_t(UINT32_MAX) + 1;
    check(ApeFile::parse(huge, &file) == ParseResult::Unsupported);

    // Extension fields and non-audio tags must not become decoder input.
    auto tagged = m;
    tagged.bytes.insert(tagged.bytes.end(), 200, 0x5a);
    check(ApeFile::parse(tagged, &file) == ParseResult::Ok);
    check(file.packet(2, &p) && p.offset + p.payloadBytes == 136);
    auto mono = m;
    put16(mono.bytes.data() + 70, 1);
    check(ApeFile::parse(mono, &file) == ParseResult::Ok && file.channels() == 1);
    for (uint16_t level : {1000, 2000, 3000}) {
        auto supported = m;
        put16(supported.bytes.data() + 52, level);
        check(ApeFile::parse(supported, &file) == ParseResult::Ok);
    }

    if (argc == 2) {
        std::ifstream input(argv[1], std::ios::binary);
        check(input.good());
        Memory sample;
        sample.bytes.assign(std::istreambuf_iterator<char>(input), {});
        check(ApeFile::parse(sample, &file) == ParseResult::Ok);
        check(file.frameCount() == 37 && file.sampleCount() == 2667168);
        check(file.durationUs() == 60480000);
        check(file.packet(2, &p) && p.offset == 319584 && p.skipBytes == 2 && p.payloadBytes == 190820);
        check(file.seekFrame(30000000, SeekMode::Previous) == 17);
        for (uint32_t i = 0; i < file.frameCount(); ++i) {
            check(file.seekFrame(file.frameTimeUs(i), SeekMode::Previous) == i);
            check(file.packet(i, &p));
            std::vector<uint8_t> data(p.size());
            check(file.readPacket(sample, i, data.data(), data.size()));
        }
    }
    std::printf("APE parser passed (%u checks)\n", checks);
}
