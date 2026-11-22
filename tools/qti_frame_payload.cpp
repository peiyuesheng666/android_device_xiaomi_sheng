// SPDX-License-Identifier: Apache-2.0
// Include the exact reviewed factory/wrapper; only this diagnostic adds frame work.
#include "../interfaces/compat/codec2/qti_payload.cpp"
#include <C2Config.h>
#include <C2PlatformSupport.h>
#include <hardware/gralloc.h>
#include <chrono>
#include <condition_variable>
#include <fstream>
#include <mutex>
#include <sys/stat.h>

namespace {
constexpr size_t kFrames = 8;
constexpr uint32_t kWidth = 128;
constexpr uint32_t kHeight = 128;

class FrameListener final : public C2Component::Listener {
public:
    void onWorkDone_nb(std::weak_ptr<C2Component>,
                       std::list<std::unique_ptr<C2Work>> items) override {
        std::lock_guard<std::mutex> lock(mutex);
        returned.splice(returned.end(), items);
        changed.notify_all();
    }
    void onTripped_nb(std::weak_ptr<C2Component>,
                      std::vector<std::shared_ptr<C2SettingResult>>) override {
        std::lock_guard<std::mutex> lock(mutex);
        tripped = true;
        changed.notify_all();
    }
    void onError_nb(std::weak_ptr<C2Component>, uint32_t code) override {
        std::lock_guard<std::mutex> lock(mutex);
        error = code ? code : C2_CORRUPTED;
        changed.notify_all();
    }
    std::mutex mutex;
    std::condition_variable changed;
    std::list<std::unique_ptr<C2Work>> returned;
    uint32_t error = 0;
    bool tripped = false;
};

int dumpFrame(const C2FrameData& frame, const char* outputDirectory, bool* seen) {
    const uint64_t timestamp = frame.ordinal.timestamp.peeku();
    if (timestamp % 125000 != 0 || timestamp / 125000 >= kFrames) return 30;
    const size_t index = timestamp / 125000;
    if (seen[index] || frame.buffers.size() != 1 || !frame.buffers[0]) return 31;
    const auto blocks = frame.buffers[0]->data().graphicBlocks();
    if (blocks.size() != 1) return 32;
    const C2GraphicView view = blocks.front().map().get();
    if (view.error() != C2_OK || !view.data()) return 33;
    const auto layout = view.layout();
    const auto crop = view.crop();
    if (layout.type != C2PlanarLayout::TYPE_YUV || layout.numPlanes < 3 ||
        crop.width != kWidth || crop.height != kHeight) return 34;
    char path[512];
    if (std::snprintf(path, sizeof(path), "%s/frame-%zu.yuv", outputDirectory, index) >=
        static_cast<int>(sizeof(path))) return 35;
    FILE* file = std::fopen(path, "wb");
    if (!file) return 36;
    int result = 0;
    for (size_t plane = 0; plane < 3 && !result; ++plane) {
        const auto& info = layout.planes[plane];
        const uint32_t divisor = plane == 0 ? 1 : 2;
        if (info.bitDepth != 8 || info.allocatedDepth != 8 || info.rightShift != 0 ||
            info.rowInc <= 0 || info.colInc <= 0 || !view.data()[plane] ||
            info.rowSampling != divisor || info.colSampling != divisor ||
            crop.left % divisor || crop.top % divisor) {
            result = 37;
            break;
        }
        uint8_t row[kWidth];
        const uint8_t* base = view.data()[plane] +
            (crop.top / divisor) * info.rowInc + (crop.left / divisor) * info.colInc;
        for (uint32_t y = 0; y < kHeight / divisor; ++y) {
            for (uint32_t x = 0; x < kWidth / divisor; ++x) {
                row[x] = base[y * info.rowInc + x * info.colInc];
            }
            if (std::fwrite(row, 1, kWidth / divisor, file) != kWidth / divisor) {
                result = 38;
                break;
            }
        }
    }
    if (std::fclose(file) != 0 && !result) result = 39;
    if (!result) {
        seen[index] = true;
        std::printf("QTI_FRAMES: output=%zu timestamp=%llu crop=%ux%u stride=%d\n",
                    index, static_cast<unsigned long long>(timestamp), crop.width,
                    crop.height, layout.planes[0].rowInc);
    }
    return result;
}
}  // namespace

extern "C" __attribute__((visibility("default")))
int sheng_qti_frame_probe_entry(const char* streamPath, const char* indexPath,
                                const char* outputDirectory) {
    if (!sandboxReady()) return 7;
    std::puts("QTI_FRAMES: no_new_privs=1 seccomp=2");
    struct stat info{};
    if (stat(streamPath, &info) || info.st_size < 1 || info.st_size > 65536) return 10;
    std::vector<uint8_t> stream(static_cast<size_t>(info.st_size));
    std::ifstream input(streamPath, std::ios::binary);
    if (!input.read(reinterpret_cast<char*>(stream.data()), stream.size())) return 11;
    std::ifstream indexFile(indexPath);
    struct InputFrame { size_t offset, size; uint64_t timestamp; } frames[kFrames];
    size_t end = 0;
    for (size_t i = 0; i < kFrames; ++i) {
        size_t ordinal;
        auto& frame = frames[i];
        if (!(indexFile >> ordinal >> frame.offset >> frame.size >> frame.timestamp) ||
            ordinal != i || frame.offset != end || frame.size == 0 ||
            frame.offset > stream.size() || frame.size > stream.size() - frame.offset ||
            frame.timestamp != i * 125000) return 12;
        end += frame.size;
    }
    std::string extra;
    if (end != stream.size() || (indexFile >> extra)) return 13;
    if (stat(outputDirectory, &info) || !S_ISDIR(info.st_mode)) return 14;

    android::ProcessState::initWithDriver("/dev/vndbinder");
    android::ProcessState::self()->startThreadPool();
    android::hardware::configureRpcThreadpool(8, false);
    auto store = getQtiComponentStore();
    if (!store) return 15;
    std::shared_ptr<C2Component> component;
    c2_status_t status = store->createComponent("c2.qti.avc.decoder", &component);
    std::printf("QTI_FRAMES: create=%d\n", status);
    if (status != C2_OK || !component) return 16;
    auto listener = std::make_shared<FrameListener>();
    status = component->setListener_vb(listener, C2_MAY_BLOCK);
    if (status != C2_OK) return 17;
    auto interface = component->intf();
    if (!interface) return 18;
    C2StreamPictureSizeInfo::output size(0u, kWidth, kHeight);
    C2StreamPixelFormatInfo::output pixelFormat(0u, HAL_PIXEL_FORMAT_YCBCR_420_888);
    C2StreamUsageTuning::output usage(0u, C2MemoryUsage::CPU_READ);
    const uint64_t outputPoolId = C2BlockPool::BASIC_GRAPHIC;
    auto outputPools = C2PortBlockPoolsTuning::output::AllocUnique({outputPoolId});
    struct Configuration { const char* name; C2Param* param; bool optional; };
    const Configuration configuration[] = {
        {"size", &size, false}, {"pixel-format", &pixelFormat, false},
        {"output-pool", outputPools.get(), false}, {"cpu-read-usage", &usage, true},
    };
    for (const auto& item : configuration) {
        std::vector<std::unique_ptr<C2SettingResult>> failures;
        status = interface->config_vb({item.param}, C2_MAY_BLOCK, &failures);
        std::printf("QTI_FRAMES: configure_%s=%d failures=%zu\n",
                    item.name, status, failures.size());
        // CCodecBufferChannel treats unsupported consumer usage as optional.
        // Actual mapping and all reference bytes must still pass below.
        if (item.optional && status == C2_BAD_INDEX && failures.empty()) continue;
        if (status != C2_OK || !failures.empty()) return 19;
    }
    std::shared_ptr<C2BlockPool> pool;
    status = android::GetCodec2BlockPool(C2BlockPool::BASIC_LINEAR, component, &pool);
    if (status != C2_OK || !pool) return 20;
    status = component->start();
    std::printf("QTI_FRAMES: start=%d\n", status);
    if (status != C2_OK) return 21;
    int result = [&]() {
        for (size_t i = 0; i < kFrames; ++i) {
            std::shared_ptr<C2LinearBlock> block;
            const auto& frame = frames[i];
            status = pool->fetchLinearBlock((frame.size + 4095) & ~size_t(4095),
                {C2MemoryUsage::CPU_READ, C2MemoryUsage::CPU_WRITE}, &block);
            if (status != C2_OK || !block) return 22;
            C2WriteView view = block->map().get();
            if (view.error() != C2_OK || view.size() < frame.size) return 23;
            std::memcpy(view.base(), stream.data() + frame.offset, frame.size);
            auto work = std::make_unique<C2Work>();
            work->input.flags = static_cast<C2FrameData::flags_t>(
                i + 1 == kFrames ? C2FrameData::FLAG_END_OF_STREAM : 0);
            work->input.ordinal.frameIndex = i;
            work->input.ordinal.timestamp = frame.timestamp;
            work->input.buffers.push_back(C2Buffer::CreateLinearBuffer(
                block->share(0, frame.size, C2Fence())));
            work->worklets.emplace_back(new C2Worklet);
            std::list<std::unique_ptr<C2Work>> batch;
            batch.push_back(std::move(work));
            status = component->queue_nb(&batch);
            std::printf("QTI_FRAMES: queue=%zu status=%d\n", i, status);
            if (status != C2_OK) return 24;
        }
        bool seen[kFrames]{};
        bool eos = false;
        size_t completed = 0;
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(15);
        while (!eos || completed < kFrames) {
            std::list<std::unique_ptr<C2Work>> returned;
            {
                std::unique_lock<std::mutex> lock(listener->mutex);
                if (!listener->changed.wait_until(lock, deadline, [&] {
                        return !listener->returned.empty() || listener->error || listener->tripped;
                    })) return 25;
                if (listener->error || listener->tripped) {
                    std::printf("QTI_FRAMES: error=%u tripped=%d\n", listener->error, listener->tripped);
                    return 26;
                }
                returned.splice(returned.end(), listener->returned);
            }
            for (const auto& work : returned) {
                if (work) {
                    std::printf("QTI_FRAMES: callback input=%llu result=%d processed=%u worklets=%zu\n",
                                static_cast<unsigned long long>(work->input.ordinal.frameIndex.peeku()),
                                work->result, work->workletsProcessed, work->worklets.size());
                    if (!work->worklets.empty() && work->worklets.front()) {
                        const auto& frame = work->worklets.front()->output;
                        std::printf("QTI_FRAMES: callback_output flags=%u buffers=%zu timestamp=%llu\n",
                                    static_cast<unsigned>(frame.flags), frame.buffers.size(),
                                    static_cast<unsigned long long>(frame.ordinal.timestamp.peeku()));
                    }
                }
                if (!work || work->result != C2_OK ||
                    work->worklets.size() != 1 || !work->worklets.front()) return 27;
                const auto& output = work->worklets.front()->output;
                const bool incomplete = (output.flags & C2FrameData::FLAG_INCOMPLETE) != 0;
                // Input-consumed callbacks may precede the decoded output.
                // They keep this work active and do not complete a worklet.
                if (work->workletsProcessed > 1 ||
                    (work->workletsProcessed == 0 && !incomplete)) return 27;
                if (!output.buffers.empty()) {
                    const int error = dumpFrame(output, outputDirectory, seen);
                    if (error) return error;
                    ++completed;
                }
                eos |= !incomplete && (output.flags & C2FrameData::FLAG_END_OF_STREAM) != 0;
            }
        }
        std::printf("QTI_FRAMES: decoded_count=%zu eos=%d\n", completed, eos);
        return 0;
    }();
    const auto stopped = component->stop();
    const auto detached = component->setListener_vb(nullptr, C2_MAY_BLOCK);
    const auto released = component->release();
    std::printf("QTI_FRAMES: stop=%d detach=%d release=%d result=%d\n",
                stopped, detached, released, result);
    pool.reset();
    interface.reset();
    component.reset();
    listener.reset();
    store.reset();
    if (!result && (stopped != C2_OK || detached != C2_OK || released != C2_OK)) result = 40;
    std::puts("QTI_FRAMES: natural process teardown pending");
    return result;
}
