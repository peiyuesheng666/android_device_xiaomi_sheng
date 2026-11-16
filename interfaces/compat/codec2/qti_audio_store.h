// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <C2Component.h>
#include <C2PlatformSupport.h>
#include <C2Work.h>
#include <codec2/hidl/1.0/Component.h>
#include <codec2/hidl/1.0/ComponentStore.h>
#include <codec2/hidl/1.0/InputBufferManager.h>
#include <log/log.h>

#include <array>
#include <memory>
#include <utility>
#include <vector>

#include "qti_alac_config.h"

namespace sheng::codec2 {

namespace c2hidl = android::hardware::media::c2::V1_0;
namespace c2utils = c2hidl::utils;

// Keep the vendor C2Component identity intact: output pools are registered
// against that object and the decoder looks them up with its own shared_ptr.
// Adapt only the configuration arriving at the HIDL queue boundary.
class AlacComponent final : public c2utils::Component {
public:
    using Component::Component;

    void initialize(const android::sp<AlacComponent>& self) {
        if (mInit != C2_OK) return;
        mInit = android::GetCodec2BlockPool(C2BlockPool::BASIC_LINEAR, mComponent, &mConfigPool);
        if (mInit != C2_OK) return;
        if (!mConfigPool) {
            mInit = C2_NO_MEMORY;
            return;
        }
        initListener(self);
    }

    android::hardware::Return<c2hidl::Status> queue(const c2hidl::WorkBundle& bundle) override {
        std::list<std::unique_ptr<C2Work>> items;
        if (!c2utils::objcpy(&items, bundle)) return c2hidl::Status::CORRUPTED;
        const c2_status_t converted = convertConfigurations(items);
        if (converted != C2_OK) return static_cast<c2hidl::Status>(converted);
        for (const auto& item : items) {
            if (item) c2utils::InputBufferManager::registerFrameData(mListener, item->input);
        }
        if (!mMultiAccessUnitHelper) {
            return static_cast<c2hidl::Status>(mComponent->queue_nb(&items));
        }
        std::list<std::list<std::unique_ptr<C2Work>>> batches;
        mMultiAccessUnitHelper->scatter(items, &batches);
        for (auto& batch : batches) {
            const c2_status_t status = mComponent->queue_nb(&batch);
            if (status != C2_OK) return static_cast<c2hidl::Status>(status);
        }
        return c2hidl::Status::OK;
    }

private:
    c2_status_t convertConfigurations(std::list<std::unique_ptr<C2Work>>& items) {
        // Stage replacements before changing ownership of any input. A caller
        // can retry an unaccepted batch without double-converting its config.
        using Replacement = std::pair<std::shared_ptr<C2Buffer>*, std::shared_ptr<C2Buffer>>;
        std::vector<Replacement> replacements;
        for (auto& work : items) {
            if (!work || !(work->input.flags & C2FrameData::FLAG_CODEC_CONFIG)) continue;
            for (auto& buffer : work->input.buffers) {
                if (!buffer) continue;
                const auto blocks = buffer->data().linearBlocks();
                if (blocks.size() != 1 || blocks[0].size() != kAlacConfigSize) continue;
                C2ReadView input = blocks[0].map().get();
                if (input.error() != C2_OK) return input.error();
                if (input.capacity() < kAlacConfigSize) return C2_CORRUPTED;
                std::array<uint8_t, kAlacConfigSize> converted;
                if (!convertAlacConfig(input.data(), kAlacConfigSize, converted.data())) continue;
                std::shared_ptr<C2LinearBlock> block;
                c2_status_t status = mConfigPool->fetchLinearBlock(kAlacConfigSize,
                        C2MemoryUsage(C2MemoryUsage::CPU_READ | C2MemoryUsage::CPU_WRITE), &block);
                if (status != C2_OK) return status;
                if (!block) return C2_NO_MEMORY;
                {
                    C2WriteView output = block->map().get();
                    if (output.error() != C2_OK) return output.error();
                    if (output.capacity() < converted.size()) return C2_CORRUPTED;
                    std::memcpy(output.data(), converted.data(), converted.size());
                }
                auto replacement = C2Buffer::CreateLinearBuffer(block->share(0, kAlacConfigSize, C2Fence()));
                if (!replacement) return C2_NO_MEMORY;
                for (const auto& info : buffer->info()) {
                    auto copy = C2Param::Copy(*info);
                    if (!copy) return C2_NO_MEMORY;
                    status = replacement->setInfo(std::shared_ptr<C2Info>(static_cast<C2Info*>(copy.release())));
                    if (status != C2_OK) return status;
                }
                replacements.emplace_back(&buffer, std::move(replacement));
            }
        }
        for (auto& [slot, replacement] : replacements) *slot = std::move(replacement);
        if (!replacements.empty()) ALOGI("Adapted ALAC initialization byte order and optional hints");
        return C2_OK;
    }

    std::shared_ptr<C2BlockPool> mConfigPool;
};

class AudioHidlStore final : public c2utils::ComponentStore {
public:
    using ComponentStore::ComponentStore;

    android::hardware::Return<void> createComponent(
            const android::hardware::hidl_string& name,
            const android::sp<c2hidl::IComponentListener>& listener,
            const android::sp<c2utils::IClientManager>& pool,
            createComponent_cb callback) override {
        if (name != "c2.qti.alac.sw.decoder" && name != "c2.qti.alac.hw.decoder") {
            return ComponentStore::createComponent(name, listener, pool, std::move(callback));
        }
        if (!listener) {
            callback(c2hidl::Status::BAD_VALUE, nullptr);
            return android::hardware::Void();
        }
        std::shared_ptr<C2Component> implementation;
        c2_status_t status = mStore->createComponent(name, &implementation);
        if (status != C2_OK || !implementation) {
            callback(static_cast<c2hidl::Status>(status == C2_OK ? C2_CORRUPTED : status), nullptr);
            return android::hardware::Void();
        }
        onInterfaceLoaded(implementation->intf());
        auto component = android::sp<AlacComponent>::make(implementation, listener,
                android::sp<c2utils::ComponentStore>::fromExisting(this), pool);
        reportComponentBirth(component.get());
        component->initialize(component);
        status = component->status();
        if (status != C2_OK) {
            (void)component->release().isOk();
            component.clear();
        }
        callback(static_cast<c2hidl::Status>(status), component);
        return android::hardware::Void();
    }
};

}  // namespace sheng::codec2
