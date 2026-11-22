// SPDX-License-Identifier: Apache-2.0
// Diagnostic only: use separate RTLD_LOCAL load groups for the OEM providers.
// No HAL registration, library patching, finalizer interception or early exit.
#include <C2Component.h>
#include <binder/ProcessState.h>
#include <dlfcn.h>
#include <hidl/HidlTransportSupport.h>
#include <link.h>
#include <minijail.h>

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <memory>

struct FieldBinding {
    const char* name;
    uintptr_t value;
    uintptr_t relocation;
};

struct Provider {
    const char* library;
    const FieldBinding* fields;
    size_t count;
};

// Derived from the exact ELF inputs; the builder records their hashes.
#include "qti-field-bindings.h"

namespace {
constexpr size_t kProviderCount = sizeof(kProviders) / sizeof(kProviders[0]);
void* handles[kProviderCount]{};
uintptr_t bases[kProviderCount]{};

const char* basenameOf(const char* path) {
    const char* slash = std::strrchr(path, '/');
    return slash ? slash + 1 : path;
}

int checkInitialLibraries(dl_phdr_info* info, size_t, void* opaque) {
    auto* valid = static_cast<bool*>(opaque);
    for (const auto& provider : kProviders) {
        if (std::strcmp(basenameOf(info->dlpi_name), provider.library) == 0) {
            std::fprintf(stderr, "QTI_GROUPS: provider loaded at startup: %s\n",
                         provider.library);
            *valid = false;
        }
    }
    return 0;
}

bool checkBindings(const char* stage) {
    size_t count = 0;
    for (size_t i = 0; i < kProviderCount; ++i) {
        if (!handles[i]) continue;
        const auto& provider = kProviders[i];
        for (size_t j = 0; j < provider.count; ++j) {
            const auto& field = provider.fields[j];
            void* actual = nullptr;
            // Read the actual GOT slot, not just dlsym's definition lookup.
            std::memcpy(&actual, reinterpret_cast<void*>(bases[i] + field.relocation),
                        sizeof(actual));
            void* expected = reinterpret_cast<void*>(bases[i] + field.value);
            if (actual != expected) {
                Dl_info owner{};
                dladdr(actual, &owner);
                std::fprintf(stderr,
                    "QTI_GROUPS: binding mismatch stage=%s library=%s symbol=%s "
                    "actual=%p expected=%p owner=%s\n", stage, provider.library,
                    field.name, actual, expected, owner.dli_fname ? owner.dli_fname : "?");
                return false;
            }
            ++count;
        }
    }
    std::printf("QTI_GROUPS: stage=%s own_object_bindings=%zu\n", stage, count);
    return true;
}

bool loadProviders() {
    for (size_t i = 0; i < kProviderCount; ++i) {
        const auto& provider = kProviders[i];
        handles[i] = dlopen(provider.library, RTLD_NOW | RTLD_LOCAL);
        if (!handles[i]) {
            std::fprintf(stderr, "QTI_GROUPS: cannot load %s: %s\n",
                         provider.library, dlerror());
            return false;
        }
        void* definition = dlsym(handles[i], provider.fields[0].name);
        Dl_info owner{};
        if (!definition || !dladdr(definition, &owner) || !owner.dli_fname ||
            std::strcmp(basenameOf(owner.dli_fname), provider.library) != 0) {
            std::fprintf(stderr, "QTI_GROUPS: definition owner mismatch: %s\n",
                         provider.library);
            return false;
        }
        bases[i] = reinterpret_cast<uintptr_t>(owner.dli_fbase);
        if (reinterpret_cast<uintptr_t>(definition) != bases[i] + provider.fields[0].value)
            return false;
        std::printf("QTI_GROUPS: provider=%s base=%p fields=%zu\n",
                    provider.library, owner.dli_fbase, provider.count);
        if (!checkBindings(provider.library)) return false;
    }
    // Retain handles until natural process teardown, matching service lifetime.
    return true;
}

std::shared_ptr<C2ComponentStore> getStore() {
    void* core = dlopen("libqcodec2_core.so", RTLD_NOW | RTLD_LOCAL);
    if (!core) {
        std::fprintf(stderr, "QTI_GROUPS: core load failed: %s\n", dlerror());
        return {};
    }
    using FactoryGetter = void* (*)(uint32_t, uint32_t);
    using StoreGetter = std::shared_ptr<C2ComponentStore> (*)(void*);
    auto getter = reinterpret_cast<FactoryGetter>(dlsym(core, "QC2ComponentStoreFactoryGetter"));
    if (!getter) return {};
    void* factory = getter(1, 0);
    if (!factory) return {};
    const unsigned char* vtable = nullptr;
    std::memcpy(&vtable, factory, sizeof(vtable));
    if (!vtable) return {};
    StoreGetter create = nullptr;
    std::memcpy(&create, vtable + 2 * sizeof(void*), sizeof(create));
    return create ? create(factory) : std::shared_ptr<C2ComponentStore>{};
}
}  // namespace

int main() {
    static_assert(sizeof(void*) == 8);
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    std::setvbuf(stderr, nullptr, _IONBF, 0);
    std::puts("QTI_GROUPS: diagnostic; no HAL registration; original seccomp enabled");
    bool initialValid = true;
    dl_iterate_phdr(checkInitialLibraries, &initialValid);
    if (!initialValid) return 1;
    android::SetUpMinijail("/vendor/etc/seccomp_policy/codec2.vendor.base-arm64.policy",
                          "/vendor/etc/seccomp_policy/codec2.vendor.ext-arm64.policy");
    android::ProcessState::initWithDriver("/dev/vndbinder");
    android::ProcessState::self()->startThreadPool();
    android::hardware::configureRpcThreadpool(8, false);
    if (!loadProviders()) return 2;
    auto store = getStore();
    if (!store || !checkBindings("factory")) return 3;
    std::printf("QTI_GROUPS: store=%s\n", store->getName().c_str());
    auto components = store->listComponents();
    std::printf("QTI_GROUPS: component_count=%zu\n", components.size());
    if (components.size() != 19) return 4;
    for (const auto& component : components) {
        if (!component || component->name.empty()) return 5;
        std::printf("QTI_GROUPS: component=%s type=%s kind=%d rank=%u\n",
                    component->name.c_str(), component->mediaType.c_str(),
                    static_cast<int>(component->kind), component->rank);
    }
    components.clear();
    store.reset();
    if (!checkBindings("store-released")) return 6;
    std::puts("QTI_GROUPS: enumeration complete; natural process teardown pending");
    return 0;
}
