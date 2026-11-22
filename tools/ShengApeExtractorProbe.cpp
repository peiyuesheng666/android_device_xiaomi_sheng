// SPDX-License-Identifier: Apache-2.0
// Isolated plugin ABI and decoder probe. It does not register an extractor,
// change codec services, render audio, or access a microphone.
#include <media/MediaExtractorPluginApi.h>
#include <media/NdkMediaCodec.h>
#include <media/NdkMediaFormat.h>

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <tuple>
#include <unistd.h>
#include <vector>

using namespace android;

static void require(bool condition, const char* message) {
    if (!condition) {
        std::fprintf(stderr, "APE_PLUGIN passed=false reason=%s\n", message);
        std::exit(1);
    }
}

struct Buffer {
    std::vector<uint8_t> bytes;
    AMediaFormat* metadata = AMediaFormat_new();
    bool busy = false;
    size_t offset = 0, length = 0;
    CMediaBuffer api{this,
        [](void* p) { static_cast<Buffer*>(p)->busy = false; },
        [](void* p) -> void* { return static_cast<Buffer*>(p)->bytes.data(); },
        [](void* p) { return static_cast<Buffer*>(p)->bytes.size(); },
        [](void* p) { return static_cast<Buffer*>(p)->offset; },
        [](void* p) { return static_cast<Buffer*>(p)->length; },
        [](void* p, size_t offset, size_t length) {
            auto* b = static_cast<Buffer*>(p);
            require(offset <= b->bytes.size() && length <= b->bytes.size() - offset, "buffer range");
            b->offset = offset;
            b->length = length;
        },
        [](void* p) { return static_cast<Buffer*>(p)->metadata; }};
    CMediaBufferGroup group{this,
        [](void* p, size_t count, size_t size, size_t) {
            require(count == 1 && size <= 8 * 1024 * 1024, "buffer allocation bound");
            static_cast<Buffer*>(p)->bytes.resize(size);
            return true;
        },
        [](void*, size_t) { require(false, "unexpected buffer allocation"); },
        [](void* p, CMediaBuffer** output, bool, size_t size) -> media_status_t {
            auto* b = static_cast<Buffer*>(p);
            require(!b->busy && size <= b->bytes.size(), "buffer ownership");
            b->busy = true;
            *output = &b->api;
            return AMEDIA_OK;
        },
        [](void* p) { return !static_cast<Buffer*>(p)->busy; }};
    ~Buffer() { AMediaFormat_delete(metadata); }
};

int main(int argc, char** argv) {
    require(argc == 4 || argc == 5, "usage: plugin.so input.ape output.pcm [seek-us]");
    const int64_t seek = argc == 5 ? std::strtoll(argv[4], nullptr, 10) : 0;
    int fd = open(argv[2], O_RDONLY | O_CLOEXEC);
    require(fd >= 0, "input file");
    CDataSource source{
        [](void* p, off64_t offset, void* data, size_t count) -> ssize_t {
            // Exercise short but successful reads, including the seek table.
            return pread(*static_cast<int*>(p), data, count > 4093 ? 4093 : count, offset);
        },
        [](void* p, off64_t* size) -> status_t {
            struct stat info{};
            if (fstat(*static_cast<int*>(p), &info)) return -1;
            *size = info.st_size;
            return 0;
        },
        [](void*) -> uint32_t { return 0; },
        [](void*, char*, size_t) { return false; }, &fd};
    void* library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!library) std::fprintf(stderr, "%s\n", dlerror());
    require(library, "plugin load");
    auto exported = reinterpret_cast<GetExtractorDef>(dlsym(library, "GETEXTRACTORDEF"));
    require(exported, "plugin export");
    auto definition = exported();
    require(definition.def_version == EXTRACTORDEF_VERSION_NDK_V2, "plugin API");
    float confidence = 0;
    void* metadata = nullptr;
    FreeMetaFunc release = nullptr;
    auto create = definition.u.v3.sniff(&source, &confidence, &metadata, &release);
    require(create && metadata && release && confidence > 0, "container sniff");
    auto* extractor = create(&source, metadata);
    release(metadata);
    require(extractor && extractor->countTracks(extractor->data) == 1, "track count");
    require(extractor->getTrack(extractor->data, 1) == nullptr, "invalid track");
    auto* format = AMediaFormat_new();
    require(extractor->getTrackMetaData(extractor->data, format, 0, 0) == AMEDIA_OK, "track format");
    const char* mime = nullptr;
    require(AMediaFormat_getString(format, AMEDIAFORMAT_KEY_MIME, &mime) &&
            std::strcmp(mime, "audio/x-ape") == 0, "track MIME");
    std::printf("APE_PLUGIN format=%s\n", AMediaFormat_toString(format));
    auto* track = extractor->getTrack(extractor->data, 0);
    require(track, "track allocation");
    Buffer buffers;
    require(track->start(track->data, &buffers.group) == AMEDIA_OK, "track start");
    // Verify the public seek modes before the decode, including negative times
    // and exact frame timestamps. The frame duration is deliberately fractional.
    for (auto [position, mode, expected] : std::vector<std::tuple<int64_t, uint32_t, int64_t>>{
            {-1, SEEK_PREVIOUS_SYNC, 0}, {30000000, SEEK_PREVIOUS_SYNC, 28421224},
            {30000000, SEEK_NEXT_SYNC, 30093061}, {30000000, SEEK_CLOSEST_SYNC, 30093061},
            {30093061, SEEK_PREVIOUS_SYNC, 30093061}, {INT64_MAX, SEEK_NEXT_SYNC, 60186122}}) {
        CMediaBuffer* b = nullptr;
        require(track->read(track->data, &b, SEEK | mode, position) == AMEDIA_OK && b, "seek read");
        int64_t timestamp = -1;
        require(AMediaFormat_getInt64(b->meta_data(b->handle), AMEDIAFORMAT_KEY_TIME_US, &timestamp) &&
                timestamp == expected, "seek timestamp");
        b->release(b->handle);
    }
    auto* codec = AMediaCodec_createCodecByName("c2.qti.ape.hw.decoder");
    require(codec, "hardware decoder allocation");
    require(AMediaCodec_configure(codec, format, nullptr, nullptr, 0) == AMEDIA_OK, "decoder configure");
    require(AMediaCodec_start(codec) == AMEDIA_OK, "decoder start");
    FILE* output = std::fopen(argv[3], "wb");
    require(output, "output file");
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(25);
    bool inputEnd = false, outputEnd = false, first = true;
    uint64_t outputBytes = 0, packets = 0;
    int64_t firstTime = -1;
    while (!outputEnd && std::chrono::steady_clock::now() < deadline) {
        if (!inputEnd) {
            ssize_t index = AMediaCodec_dequeueInputBuffer(codec, 1000);
            if (index >= 0) {
                CMediaBuffer* b = nullptr;
                auto status = track->read(track->data, &b, first ? SEEK | SEEK_PREVIOUS_SYNC : 0, seek);
                if (status == AMEDIA_ERROR_END_OF_STREAM) {
                    require(AMediaCodec_queueInputBuffer(codec, index, 0, 0, 0,
                            AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM) == AMEDIA_OK, "input EOS");
                    inputEnd = true;
                } else {
                    require(status == AMEDIA_OK && b, "packet read");
                    size_t capacity = 0;
                    auto* input = AMediaCodec_getInputBuffer(codec, index, &capacity);
                    const auto size = b->range_length(b->handle);
                    require(input && size <= capacity, "codec input capacity");
                    std::memcpy(input, static_cast<uint8_t*>(b->data(b->handle)) +
                            b->range_offset(b->handle), size);
                    int64_t timestamp = 0;
                    require(AMediaFormat_getInt64(b->meta_data(b->handle), AMEDIAFORMAT_KEY_TIME_US,
                            &timestamp), "packet timestamp");
                    if (first) firstTime = timestamp;
                    b->release(b->handle);
                    require(AMediaCodec_queueInputBuffer(codec, index, 0, size, timestamp, 0) == AMEDIA_OK,
                            "queue packet");
                    ++packets;
                }
                first = false;
            }
        }
        AMediaCodecBufferInfo info{};
        const auto index = AMediaCodec_dequeueOutputBuffer(codec, &info, 1000);
        if (index == AMEDIACODEC_INFO_OUTPUT_FORMAT_CHANGED) {
            auto* decodedFormat = AMediaCodec_getOutputFormat(codec);
            int32_t rate = 0, channels = 0, encoding = 2;
            require(AMediaFormat_getInt32(decodedFormat, AMEDIAFORMAT_KEY_SAMPLE_RATE, &rate) &&
                    AMediaFormat_getInt32(decodedFormat, AMEDIAFORMAT_KEY_CHANNEL_COUNT, &channels),
                    "decoded format");
            AMediaFormat_getInt32(decodedFormat, AMEDIAFORMAT_KEY_PCM_ENCODING, &encoding);
            require(rate == 44100 && channels == 2 && encoding == 2, "reference PCM format");
            AMediaFormat_delete(decodedFormat);
        } else if (index >= 0) {
            if (info.size > 0 && !(info.flags & AMEDIACODEC_BUFFER_FLAG_CODEC_CONFIG)) {
                size_t capacity = 0;
                auto* data = AMediaCodec_getOutputBuffer(codec, index, &capacity);
                require(data && info.offset >= 0 && size_t(info.offset) <= capacity &&
                        size_t(info.size) <= capacity - info.offset, "output range");
                require(std::fwrite(data + info.offset, 1, info.size, output) == size_t(info.size), "write PCM");
                outputBytes += info.size;
                require(outputBytes <= 16 * 1024 * 1024, "output bound");
            }
            outputEnd = info.flags & AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM;
            require(AMediaCodec_releaseOutputBuffer(codec, index, false) == AMEDIA_OK, "release output");
        }
    }
    require(std::fclose(output) == 0, "close output");
    require(inputEnd && outputEnd, "stream completion");
    require(AMediaCodec_stop(codec) == AMEDIA_OK, "decoder stop");
    AMediaCodec_delete(codec);
    require(track->stop(track->data) == AMEDIA_OK, "track stop");
    track->free(track->data);
    std::free(track);
    extractor->free(extractor->data);
    std::free(extractor);
    AMediaFormat_delete(format);
    close(fd);
    require(dlclose(library) == 0, "plugin unload");
    std::printf("APE_PLUGIN passed=true bytes=%llu packets=%llu first_time_us=%lld "
            "registered=false playback=false microphone=false\n",
            static_cast<unsigned long long>(outputBytes), static_cast<unsigned long long>(packets),
            static_cast<long long>(firstTime));
}
