// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <utility>
#include <vector>

namespace sheng::ape {

// Readers supply a stable length and either read the entire requested range or
// return false. Offsets refer to the container, including its descriptor.
class ByteSource {
public:
    virtual ~ByteSource() = default;
    virtual uint64_t size() const = 0;
    virtual bool readAt(uint64_t offset, void* data, size_t count) = 0;
};

inline uint16_t le16(const uint8_t* p) {
    return uint16_t(p[0]) | (uint16_t(p[1]) << 8);
}

inline uint32_t le32(const uint8_t* p) {
    return uint32_t(p[0]) | (uint32_t(p[1]) << 8) |
            (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
}

inline void put16(uint8_t* p, uint16_t value) {
    p[0] = value;
    p[1] = value >> 8;
}

inline void put32(uint8_t* p, uint32_t value) {
    for (unsigned i = 0; i != 4; ++i) p[i] = value >> (i * 8);
}

enum class ParseResult { Ok, Malformed, Unsupported, IoError };
enum class SeekMode { Previous, Next, Closest, FrameIndex };

struct Packet {
    uint64_t offset;
    uint32_t payloadBytes;
    uint32_t skipBytes;
    uint32_t index;
    int64_t timeUs;
    size_t size() const { return size_t(payloadBytes) + 12; }
};

class ApeFile {
public:
    static constexpr uint32_t kMaxFrames = 1u << 20;
    static constexpr uint32_t kMaxPacketBytes = 8u << 20;

    static ParseResult parse(ByteSource& source, ApeFile* output) {
        if (!output) return ParseResult::Malformed;
        *output = ApeFile();
        ApeFile candidate;
        const auto result = candidate.readHeader(source);
        if (result == ParseResult::Ok) *output = std::move(candidate);
        return result;
    }

    uint32_t sampleRate() const { return mSampleRate; }
    uint16_t channels() const { return mChannels; }
    uint16_t bitsPerSample() const { return mBits; }
    uint16_t compressionLevel() const { return mCompression; }
    uint32_t frameCount() const { return mOffsets.size(); }
    uint32_t maxPacketBytes() const { return mMaxPacket; }
    uint64_t sampleCount() const { return mSamples; }
    int64_t durationUs() const { return mSampleRate ? mSamples * 1000000 / mSampleRate : 0; }
    int64_t frameTimeUs(uint32_t index) const {
        if (index >= frameCount()) return durationUs();
        return mSampleRate ? uint64_t(index) * mBlocks * 1000000 / mSampleRate : 0;
    }

    std::array<uint8_t, 32> codecConfig() const {
        std::array<uint8_t, 32> data{};
        put16(data.data(), mVersion);
        put16(data.data() + 2, mCompression);
        put32(data.data() + 4, mFlags);
        put32(data.data() + 8, mBlocks);
        put32(data.data() + 12, mFinalBlocks);
        put32(data.data() + 16, frameCount());
        put16(data.data() + 20, mBits);
        put16(data.data() + 22, mChannels);
        put32(data.data() + 24, mSampleRate);
        put32(data.data() + 28, 1);
        return data;
    }

    bool packet(uint32_t index, Packet* result) const {
        if (!result || index >= mOffsets.size()) return false;
        const uint32_t skip = (mOffsets[index] - mOffsets.front()) & 3;
        const uint64_t start = uint64_t(mOffsets[index]) - skip;
        const uint64_t end = index + 1 < mOffsets.size() ? mOffsets[index + 1] : mDataEnd;
        if (end <= start) return false;
        // The next packet owns the remaining word. Rounding up duplicates it
        // and shifts the Qualcomm decoder's subsequent packet boundaries.
        const uint64_t payload = (end - start) & ~uint64_t(3);
        if (payload <= skip || payload > kMaxPacketBytes - 12) return false;
        *result = {start, uint32_t(payload), skip, index, frameTimeUs(index)};
        return true;
    }

    bool readPacket(ByteSource& source, uint32_t index, void* data, size_t capacity) const {
        Packet p{};
        if (!data || !packet(index, &p) || capacity < p.size() ||
                p.offset > source.size() || p.payloadBytes > source.size() - p.offset) {
            return false;
        }
        auto* bytes = static_cast<uint8_t*>(data);
        if (!source.readAt(p.offset, bytes + 12, p.payloadBytes)) return false;
        put32(bytes, p.payloadBytes);
        put32(bytes + 4, p.skipBytes);
        put32(bytes + 8, index);
        return true;
    }

    uint32_t seekFrame(int64_t position, SeekMode mode) const {
        if (mOffsets.empty() || position <= 0) return 0;
        const uint32_t last = frameCount() - 1;
        if (mode == SeekMode::FrameIndex) return std::min<uint64_t>(position, last);
        if (position >= frameTimeUs(last)) return last;
        // Compare timestamps directly: converting a rounded microsecond time
        // back to samples can otherwise select the preceding frame.
        uint32_t low = 0, high = last;
        while (low < high) {
            const uint32_t middle = low + (high - low) / 2;
            if (frameTimeUs(middle) < position) low = middle + 1;
            else high = middle;
        }
        if (frameTimeUs(low) == position || mode == SeekMode::Next) return low;
        if (mode == SeekMode::Closest &&
                frameTimeUs(low) - position < position - frameTimeUs(low - 1)) return low;
        return low - 1;
    }

private:
    ParseResult readHeader(ByteSource& source) {
        // The supported seek table stores absolute 32-bit offsets. Reject
        // larger containers rather than guessing how wrapped offsets relate.
        if (source.size() < 76) return ParseResult::Malformed;
        if (source.size() > UINT32_MAX) return ParseResult::Unsupported;
        std::array<uint8_t, 52> descriptor{};
        if (!source.readAt(0, descriptor.data(), descriptor.size())) return ParseResult::IoError;
        if (std::memcmp(descriptor.data(), "MAC ", 4)) return ParseResult::Malformed;
        mVersion = le16(descriptor.data() + 4);
        if (mVersion < 3980 || mVersion > 3990) return ParseResult::Unsupported;
        const uint64_t descriptorBytes = le32(descriptor.data() + 8);
        const uint64_t headerBytes = le32(descriptor.data() + 12);
        const uint64_t seekBytes = le32(descriptor.data() + 16);
        const uint64_t waveBytes = le32(descriptor.data() + 20);
        const uint64_t audioBytes = le32(descriptor.data() + 24) |
                (uint64_t(le32(descriptor.data() + 28)) << 32);
        const uint64_t tailBytes = le32(descriptor.data() + 32);
        if (descriptorBytes < 52 || headerBytes < 24 ||
                descriptorBytes > source.size() || headerBytes > source.size() - descriptorBytes ||
                seekBytes > uint64_t(kMaxFrames) * 4 || (seekBytes & 3)) {
            return ParseResult::Malformed;
        }
        const uint64_t seekStart = descriptorBytes + headerBytes;
        if (seekBytes > source.size() - seekStart) return ParseResult::Malformed;
        const uint64_t waveStart = seekStart + seekBytes;
        if (waveBytes > source.size() - waveStart) return ParseResult::Malformed;
        const uint64_t dataStart = waveStart + waveBytes;
        if (!audioBytes || audioBytes > source.size() - dataStart) return ParseResult::Malformed;
        mDataEnd = dataStart + audioBytes;
        if (tailBytes > source.size() - mDataEnd) return ParseResult::Malformed;

        std::array<uint8_t, 24> header{};
        if (!source.readAt(descriptorBytes, header.data(), header.size())) return ParseResult::IoError;
        mCompression = le16(header.data());
        mFlags = le16(header.data() + 2);
        mBlocks = le32(header.data() + 4);
        mFinalBlocks = le32(header.data() + 8);
        const uint32_t frames = le32(header.data() + 12);
        mBits = le16(header.data() + 16);
        mChannels = le16(header.data() + 18);
        mSampleRate = le32(header.data() + 20);
        if (!frames || frames > kMaxFrames || seekBytes < uint64_t(frames) * 4 ||
                !mBlocks || mBlocks > 294912 || !mFinalBlocks || mFinalBlocks > mBlocks) {
            return ParseResult::Malformed;
        }
        // The available DSP decoder rejects extra-high and insane compression.
        // Advertise only the PCM layout and compression range it can accept.
        if ((mCompression != 1000 && mCompression != 2000 && mCompression != 3000) ||
                mBits != 16 || mChannels < 1 || mChannels > 2 ||
                mSampleRate < 8000 || mSampleRate > 192000 || (mFlags & ~uint16_t(32))) {
            return ParseResult::Unsupported;
        }
        mSamples = uint64_t(frames - 1) * mBlocks + mFinalBlocks;
        mOffsets.resize(frames);
        std::array<uint8_t, 4096> table{};
        for (uint32_t index = 0; index < frames;) {
            const uint32_t count = std::min<uint32_t>(frames - index, table.size() / 4);
            if (!source.readAt(seekStart + uint64_t(index) * 4, table.data(), count * 4)) {
                return ParseResult::IoError;
            }
            for (uint32_t j = 0; j < count; ++j, ++index) {
                const uint32_t offset = le32(table.data() + j * 4);
                if (offset < dataStart || offset >= mDataEnd ||
                        (index == 0 && offset != dataStart) ||
                        (index != 0 && offset <= mOffsets[index - 1])) {
                    return ParseResult::Malformed;
                }
                mOffsets[index] = offset;
            }
        }
        for (uint32_t i = 0; i < frames; ++i) {
            Packet p{};
            if (!packet(i, &p)) return ParseResult::Malformed;
            mMaxPacket = std::max<uint32_t>(mMaxPacket, p.size());
        }
        return ParseResult::Ok;
    }

    uint16_t mVersion = 0, mCompression = 0, mFlags = 0, mBits = 0, mChannels = 0;
    uint32_t mBlocks = 0, mFinalBlocks = 0, mSampleRate = 0, mMaxPacket = 0;
    uint64_t mSamples = 0, mDataEnd = 0;
    std::vector<uint32_t> mOffsets;
};

}  // namespace sheng::ape
