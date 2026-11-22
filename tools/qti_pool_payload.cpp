// SPDX-License-Identifier: Apache-2.0
// Exercise HIDL pool ownership with the unchanged production component.
#include "../interfaces/compat/codec2/qti_payload.cpp"

namespace {
namespace c2hidl = android::hardware::media::c2::V1_0;

class AudioProbeListener final : public c2hidl::IComponentListener {
public:
    android::hardware::Return<void> onWorkDone(const c2hidl::WorkBundle&) override {
        return android::hardware::Void();
    }
    android::hardware::Return<void> onTripped(
            const android::hardware::hidl_vec<c2hidl::SettingResult>&) override {
        return android::hardware::Void();
    }
    android::hardware::Return<void> onError(c2hidl::Status, uint32_t) override {
        return android::hardware::Void();
    }
    android::hardware::Return<void> onFramesRendered(
            const android::hardware::hidl_vec<RenderedFrame>&) override {
        return android::hardware::Void();
    }
    android::hardware::Return<void> onInputBuffersReleased(
            const android::hardware::hidl_vec<InputBuffer>&) override {
        return android::hardware::Void();
    }
};

bool probeAlacOutputPool(const std::shared_ptr<C2Component>& implementation,
                         const android::sp<c2hidl::utils::ComponentStore>& store) {
    auto listener = android::sp<AudioProbeListener>::make();
    auto component = android::sp<sheng::codec2::AlacComponent>::make(
            implementation, listener, store, android::sp<c2hidl::utils::IClientManager>{});
    component->initialize(component);
    if (component->status() != C2_OK) return false;
    c2hidl::Status created = c2hidl::Status::CORRUPTED;
    uint64_t id = 0;
    const bool transaction = component->createBlockPool(C2AllocatorStore::DEFAULT_LINEAR,
            [&](c2hidl::Status status, uint64_t poolId, const auto&) {
                created = status;
                id = poolId;
            }).isOk();
    std::shared_ptr<C2BlockPool> pool;
    const c2_status_t found = transaction && created == c2hidl::Status::OK
            ? android::GetCodec2BlockPool(id, implementation, &pool) : C2_CORRUPTED;
    std::shared_ptr<C2LinearBlock> block;
    const c2_status_t allocated = found == C2_OK && pool
            ? pool->fetchLinearBlock(4096,
                    C2MemoryUsage(C2MemoryUsage::CPU_READ | C2MemoryUsage::CPU_WRITE), &block)
            : C2_CORRUPTED;
    std::printf("QTI_PAYLOAD: alac_hidl_pool=%s status=%d id=%llu allocated=%d\n",
                implementation->intf()->getName().c_str(), found,
                static_cast<unsigned long long>(id), allocated);
    bool passed = found == C2_OK && allocated == C2_OK && block != nullptr;
    block.reset();
    pool.reset();
    if (created == c2hidl::Status::OK) {
        auto destroyed = component->destroyBlockPool(id);
        passed = destroyed.isOk() && destroyed == c2hidl::Status::OK && passed;
    }
    auto released = component->release();
    return released.isOk() && released == c2hidl::Status::OK && passed;
}
}  // namespace

extern "C" __attribute__((visibility("default")))
int sheng_qti_pool_probe_entry() {
    if (!sandboxReady()) return 7;
    android::ProcessState::initWithDriver("/dev/vndbinder");
    android::ProcessState::self()->startThreadPool();
    android::hardware::configureRpcThreadpool(8, false);
    auto implementation = getQtiComponentStore();
    if (!implementation) return 1;
    auto store = makeQtiHidlStore(implementation);
    if (store->status() != C2_OK) return 2;
    for (const char* name : {"c2.qti.alac.sw.decoder", "c2.qti.alac.hw.decoder"}) {
        std::shared_ptr<C2Component> component;
        if (implementation->createComponent(name, &component) != C2_OK || !component) return 3;
        if (!probeAlacOutputPool(component, store)) return 4;
        component.reset();
    }
    store.clear();
    implementation.reset();
    // InputBufferManager is a process-lifetime platform singleton with a
    // joinable std::thread and no shutdown API. All component/pool objects
    // above are released; the runner stops this test service with SIGTERM.
    // Production factory enumeration separately checks natural teardown.
    std::puts("QTI_POOL_PROBE: components and pools released; ready for SIGTERM");
    android::hardware::joinRpcThreadpool();
    return 5;
}
