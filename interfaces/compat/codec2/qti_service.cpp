// SPDX-License-Identifier: Apache-2.0
#define LOG_TAG "ShengQtiCodec2"

#include <C2Component.h>
#include <binder/ProcessState.h>
#include <codec2/hidl/1.0/ComponentStore.h>
#include <dlfcn.h>
#include <hidl/HidlTransportSupport.h>
#include <log/log.h>
#if !defined(SHENG_QTI_SANDBOX_ALREADY_SET)
#include <minijail.h>
#endif
#include <signal.h>
#include <string.h>

#include <cstdint>
#include <memory>

#include "qti_profile.h"
#if defined(SHENG_QTI_AUDIO)
#include "qti_audio_store.h"
#endif

#if !defined(__aarch64__)
#error "The reviewed sheng QTI factory ABI requires AArch64"
#endif

namespace {

// The sheng OEM exposes a versioned factory entry point, without a public
// header. This bridge describes its reviewed AArch64 ABI, rather than declaring
// an unrelated C++ class and using its vptr. The 1.0 factory has two destructor
// entries followed by the store getter, returning shared_ptr<C2ComponentStore>.
// See README-qti.md for the input identities and matching OEM call sites.
using FactoryGetter = void* (*)(uint32_t major, uint32_t minor);
using StoreGetter = std::shared_ptr<C2ComponentStore> (*)(void* factory);

std::shared_ptr<C2ComponentStore> getQtiComponentStore() {
    // Keep this DSO and its factory alive for the process lifetime, as the OEM
    // service does. Store objects, component callbacks and their destructors
    // retain code in this library after service registration.
    void* library = dlopen(kLibrary, RTLD_NOW | RTLD_LOCAL);
    if (library == nullptr) {
        ALOGE("Cannot load %s: %s", kLibrary, dlerror());
        return {};
    }
    auto getter = reinterpret_cast<FactoryGetter>(dlsym(library, kFactoryGetter));
    if (getter == nullptr) {
        ALOGE("Cannot resolve %s: %s", kFactoryGetter, dlerror());
        return {};
    }
    void* factory = getter(1, 0);
    if (factory == nullptr) {
        ALOGE("QTI component-store factory does not support version 1.0");
        return {};
    }

    // memcpy makes this a byte-level ABI read, with no type-punning of an OEM
    // C++ object. The OEM vtable entry receives this in x0 and returns the
    // nontrivial shared_ptr through x8, exactly as its original main does.
    const unsigned char* vtable = nullptr;
    memcpy(&vtable, factory, sizeof(vtable));
    if (vtable == nullptr) {
        ALOGE("QTI component-store factory has no vtable");
        return {};
    }
    StoreGetter createStore = nullptr;
    static_assert(sizeof(createStore) == sizeof(void*));
    memcpy(&createStore, vtable + 2 * sizeof(void*), sizeof(createStore));
    if (createStore == nullptr) {
        ALOGE("QTI component-store factory has no store getter");
        return {};
    }
    return createStore(factory);
}

android::sp<android::hardware::media::c2::V1_0::utils::ComponentStore> makeQtiHidlStore(
        const std::shared_ptr<C2ComponentStore>& implementation) {
#if defined(SHENG_QTI_AUDIO)
    return android::sp<sheng::codec2::AudioHidlStore>::make(implementation);
#else
    return android::sp<android::hardware::media::c2::V1_0::utils::ComponentStore>::make(implementation);
#endif
}

}  // namespace

int main(int argc, char** argv) {
    using android::hardware::media::c2::V1_0::utils::ComponentStore;
    static_assert(sizeof(void*) == 8);

    signal(SIGPIPE, SIG_IGN);
#if !defined(SHENG_QTI_SANDBOX_ALREADY_SET)
    android::SetUpMinijail(kBaseSeccompPolicy, kExtraSeccompPolicy);
#endif
    if (argc > 0 && argv != nullptr && argv[0] != nullptr) {
        strlcpy(argv[0], kShengQtiProcessName, strlen(argv[0]));
    }
    android::ProcessState::initWithDriver("/dev/vndbinder");
    android::ProcessState::self()->startThreadPool();
    android::hardware::configureRpcThreadpool(8, true);

    auto implementation = getQtiComponentStore();
    if (implementation == nullptr) {
        ALOGE("QTI component store is unavailable");
        return 1;
    }
    // OEM main allocates 264 bytes before calling the platform constructor.
    // Build the wrapper against its provider's current headers instead.
    auto store = makeQtiHidlStore(implementation);
    if (store->status() != C2_OK) {
        ALOGE("QTI store initialization failed: %d", store->status());
        return 1;
    }
    const android::status_t status = store->registerAsService(kShengQtiInstance);
    if (status != android::OK) {
        ALOGE("QTI store registration failed: %d", status);
        return 1;
    }
    ALOGI("%s: registered, ComponentStore size=%zu", kShengQtiInstance, sizeof(ComponentStore));
    android::hardware::joinRpcThreadpool();
    return 1;
}
