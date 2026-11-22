// SPDX-License-Identifier: Apache-2.0
// Exercise the exact source-service factory bridge without registering a HAL.
#define main sheng_qti_service_main_not_called
#include "../interfaces/compat/codec2/qti_service.cpp"
#undef main

#include <cstdio>

#if defined(SHENG_QTI_FACTORY_DIAGNOSE_EXIT)
#include <atomic>

namespace {
struct ExitCallback {
    void (*function)(void*);
    void* argument;
};
ExitCallback exitCallbacks[4096];
std::atomic<unsigned> exitCallbackCount{0};

void traceExitCallback(void* opaque) {
    auto* entry = static_cast<ExitCallback*>(opaque);
    Dl_info info{};
    dladdr(reinterpret_cast<void*>(entry->function), &info);
    std::fprintf(stderr, "QTI_EXIT: callback=%p argument=%p library=%s symbol=%s\n",
                 reinterpret_cast<void*>(entry->function), entry->argument,
                 info.dli_fname ? info.dli_fname : "?", info.dli_sname ? info.dli_sname : "?");
    entry->function(entry->argument);
}
}  // namespace

extern "C" int __cxa_atexit(void (*function)(void*), void* argument, void* dso) {
    using Register = int (*)(void (*)(void*), void*, void*);
    auto realRegister = reinterpret_cast<Register>(dlsym(RTLD_NEXT, "__cxa_atexit"));
    const unsigned index = exitCallbackCount.fetch_add(1);
    if (realRegister == nullptr || index >= 4096) return -1;
    exitCallbacks[index] = {function, argument};
    return realRegister(traceExitCallback, &exitCallbacks[index], dso);
}
#endif

int main() {
    // Preserve diagnostics even if an OEM factory aborts or blocks. The caller
    // must run this temporary probe with an external, bounded timeout.
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    std::setvbuf(stderr, nullptr, _IONBF, 0);
    std::puts("QTI_FACTORY_PROBE: starting; no HAL registration");
    signal(SIGPIPE, SIG_IGN);
#if defined(SHENG_QTI_FACTORY_DIAGNOSE_EXIT)
    // Diagnostic-only variant: the OEM seccomp policy blocks getppid in
    // debuggerd's abort handler, hiding the original Scudo backtrace.
    std::puts("QTI_FACTORY_PROBE: diagnostic exit build; seccomp not installed");
#else
    android::SetUpMinijail(kBaseSeccompPolicy, kExtraSeccompPolicy);
#endif
    android::ProcessState::initWithDriver("/dev/vndbinder");
    android::ProcessState::self()->startThreadPool();
    android::hardware::configureRpcThreadpool(8, false);

    std::puts("QTI_FACTORY_PROBE: opening reviewed OEM factory version 1.0");
    auto implementation = getQtiComponentStore();
    if (implementation == nullptr) {
        std::fputs("QTI_FACTORY_PROBE: factory/store unavailable\n", stderr);
        return 1;
    }
    std::printf("QTI_FACTORY_PROBE: store=%s platform_wrapper_size=%zu\n",
                implementation->getName().c_str(),
                sizeof(android::hardware::media::c2::V1_0::utils::ComponentStore));
    const auto components = implementation->listComponents();
    std::printf("QTI_FACTORY_PROBE: listComponents count=%zu\n", components.size());
    if (components.empty()) {
        std::fputs("QTI_FACTORY_PROBE: empty component list\n", stderr);
        return 1;
    }
    for (const auto& component : components) {
        if (component == nullptr || component->name.empty()) {
            std::fputs("QTI_FACTORY_PROBE: null or unnamed component\n", stderr);
            return 1;
        }
        std::printf("QTI_FACTORY_PROBE: component=%s type=%s kind=%d rank=%u\n",
                    component->name.c_str(), component->mediaType.c_str(),
                    static_cast<int>(component->kind), component->rank);
    }
    implementation.reset();
    std::puts("QTI_FACTORY_PROBE: enumeration complete; process teardown pending");
    return 0;
}
