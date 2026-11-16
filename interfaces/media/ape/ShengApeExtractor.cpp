// SPDX-License-Identifier: Apache-2.0
#define LOG_TAG "ShengApeExtractor"

#include <media/MediaExtractorPluginHelper.h>
#include <media/NdkMediaFormat.h>

#include <memory>

#include "ApeFile.h"

namespace {
using namespace android;
using sheng::ape::ApeFile;
using sheng::ape::Packet;
constexpr char kMime[] = "audio/x-ape";

class Source final : public sheng::ape::ByteSource {
public:
    explicit Source(CDataSource* source) : mSource(source) {
        off64_t size = 0;
        if (source && source->getSize && source->readAt &&
                source->getSize(source->handle, &size) == OK && size >= 0) mSize = size;
    }
    uint64_t size() const override { return mSize; }
    bool readAt(uint64_t offset, void* data, size_t count) override {
        if (offset > mSize || count > mSize - offset) return false;
        auto* target = static_cast<uint8_t*>(data);
        while (count) {
            const ssize_t got = mSource->readAt(mSource->handle, offset, target, count);
            if (got <= 0 || uint64_t(got) > count) return false;
            offset += got;
            target += got;
            count -= got;
        }
        return true;
    }
private:
    CDataSource* mSource;
    uint64_t mSize = 0;
};

void trackFormat(const ApeFile& file, AMediaFormat* format) {
    AMediaFormat_clear(format);
    AMediaFormat_setString(format, AMEDIAFORMAT_KEY_MIME, kMime);
    AMediaFormat_setInt32(format, AMEDIAFORMAT_KEY_SAMPLE_RATE, file.sampleRate());
    AMediaFormat_setInt32(format, AMEDIAFORMAT_KEY_CHANNEL_COUNT, file.channels());
    AMediaFormat_setInt32(format, AMEDIAFORMAT_KEY_PCM_ENCODING, 2); // PCM 16-bit
    AMediaFormat_setInt32(format, AMEDIAFORMAT_KEY_MAX_INPUT_SIZE, file.maxPacketBytes());
    AMediaFormat_setInt64(format, AMEDIAFORMAT_KEY_DURATION, file.durationUs());
    const auto config = file.codecConfig();
    AMediaFormat_setBuffer(format, AMEDIAFORMAT_KEY_CSD_0, config.data(), config.size());
}

class Track final : public MediaTrackHelper {
public:
    Track(CDataSource* source, std::shared_ptr<const ApeFile> file)
        : mSource(source), mFile(std::move(file)) {}

    media_status_t start() override {
        if (mStarted || !mBufferGroup) return AMEDIA_ERROR_INVALID_OPERATION;
        if (!mBufferGroup->init(1, mFile->maxPacketBytes(), 2)) return AMEDIA_ERROR_UNKNOWN;
        mNext = 0;
        mStarted = true;
        return AMEDIA_OK;
    }
    media_status_t stop() override {
        mStarted = false;
        return AMEDIA_OK;
    }
    media_status_t getFormat(AMediaFormat* format) override {
        trackFormat(*mFile, format);
        return AMEDIA_OK;
    }
    media_status_t read(MediaBufferHelper** output, const ReadOptions* options) override {
        *output = nullptr;
        if (!mStarted) return AMEDIA_ERROR_INVALID_OPERATION;
        int64_t requestedTime = 0;
        ReadOptions::SeekMode mode;
        if (options && options->getSeekTo(&requestedTime, &mode)) {
            auto seekMode = sheng::ape::SeekMode::Previous;
            switch (mode) {
                case ReadOptions::SEEK_NEXT_SYNC: seekMode = sheng::ape::SeekMode::Next; break;
                case ReadOptions::SEEK_CLOSEST_SYNC: seekMode = sheng::ape::SeekMode::Closest; break;
                case ReadOptions::SEEK_FRAME_INDEX: seekMode = sheng::ape::SeekMode::FrameIndex; break;
                case ReadOptions::SEEK_CLOSEST:
                case ReadOptions::SEEK_PREVIOUS_SYNC: break;
                default: return AMEDIA_ERROR_UNSUPPORTED;
            }
            mNext = mFile->seekFrame(requestedTime, seekMode);
        }
        if (mNext >= mFile->frameCount()) return AMEDIA_ERROR_END_OF_STREAM;
        Packet packet{};
        if (!mFile->packet(mNext, &packet)) return AMEDIA_ERROR_MALFORMED;
        MediaBufferHelper* buffer = nullptr;
        const auto result = mBufferGroup->acquire_buffer(&buffer, false, packet.size());
        if (result != AMEDIA_OK) return result;
        if (!buffer) return AMEDIA_ERROR_UNKNOWN;
        if (!mFile->readPacket(mSource, mNext, buffer->data(), buffer->size())) {
            buffer->release();
            return AMEDIA_ERROR_IO;
        }
        buffer->set_range(0, packet.size());
        auto* metadata = buffer->meta_data();
        AMediaFormat_clear(metadata);
        AMediaFormat_setInt64(metadata, AMEDIAFORMAT_KEY_TIME_US, packet.timeUs);
        AMediaFormat_setInt32(metadata, AMEDIAFORMAT_KEY_IS_SYNC_FRAME, 1);
        ++mNext;
        *output = buffer;
        return AMEDIA_OK;
    }
private:
    Source mSource;
    std::shared_ptr<const ApeFile> mFile;
    uint32_t mNext = 0;
    bool mStarted = false;
};

class Extractor final : public MediaExtractorPluginHelper {
public:
    Extractor(CDataSource* source, const ApeFile& file)
        : mSource(source), mFile(std::make_shared<ApeFile>(file)) {}
    size_t countTracks() override { return 1; }
    MediaTrackHelper* getTrack(size_t index) override {
        return index == 0 ? new Track(mSource, mFile) : nullptr;
    }
    media_status_t getTrackMetaData(AMediaFormat* format, size_t index, uint32_t) override {
        if (index != 0) return AMEDIA_ERROR_INVALID_PARAMETER;
        trackFormat(*mFile, format);
        return AMEDIA_OK;
    }
    media_status_t getMetaData(AMediaFormat* format) override {
        AMediaFormat_clear(format);
        AMediaFormat_setString(format, AMEDIAFORMAT_KEY_MIME, kMime);
        AMediaFormat_setInt64(format, AMEDIAFORMAT_KEY_DURATION, mFile->durationUs());
        return AMEDIA_OK;
    }
    const char* name() override { return "ShengApeExtractor"; }
private:
    CDataSource* mSource;
    std::shared_ptr<const ApeFile> mFile;
};

CMediaExtractor* create(CDataSource* source, void* metadata) {
    if (!source || !metadata) return nullptr;
    return wrap(new Extractor(source, *static_cast<ApeFile*>(metadata)));
}

CreatorFunc sniff(CDataSource* source, float* confidence, void** metadata, FreeMetaFunc* release) {
    if (!source || !confidence || !metadata || !release) return nullptr;
    *metadata = nullptr;
    *release = nullptr;
    Source input(source);
    auto file = std::make_unique<ApeFile>();
    if (ApeFile::parse(input, file.get()) != sheng::ape::ParseResult::Ok) return nullptr;
    *confidence = 0.8f;
    *metadata = file.release();
    *release = [](void* data) { delete static_cast<ApeFile*>(data); };
    return create;
}

const char* kTypes[] = {"ape", kMime, nullptr};
}  // namespace

extern "C" __attribute__((visibility("default"))) android::ExtractorDef GETEXTRACTORDEF() {
    return {android::EXTRACTORDEF_VERSION,
            {{0x85, 0xd6, 0x75, 0x0e, 0x19, 0x5b, 0x4e, 0x88,
              0x97, 0x84, 0xa3, 0x7f, 0xba, 0x8c, 0x20, 0x51}},
            1, "Sheng APE extractor", {.v3 = {sniff, kTypes}}};
}
