// SPDX-License-Identifier: Apache-2.0
#define LOG_TAG "ShengQtiBootstrap"

#include <dlfcn.h>
#include <link.h>
#include <log/log.h>
#include <minijail.h>
#include <signal.h>

#include <cstdio>
#include <cstring>

#include "qti_load_groups.h"
#include "qti_profile.h"

namespace {
int rejectStartupProviders(dl_phdr_info* info, size_t, void* opaque) {
    auto* valid = static_cast<bool*>(opaque);
    const char* slash = std::strrchr(info->dlpi_name, '/');
    const char* name = slash ? slash + 1 : info->dlpi_name;
    for (const char* provider : kShengQtiProviderLibraries) {
        if (std::strcmp(name, provider) == 0) {
            ALOGE("C2 provider unexpectedly loaded through bootstrap DT_NEEDED: %s", provider);
            *valid = false;
        }
    }
    return 0;
}
}  // namespace

int main(int argc, char** argv) {
    // A separate, lightweight executable is necessary: a service executable
    // with a startup VNDK dependency makes that provider globally visible.
    bool startupValid = true;
    dl_iterate_phdr(rejectStartupProviders, &startupValid);
    if (!startupValid) return 1;
    signal(SIGPIPE, SIG_IGN);
    android::SetUpMinijail(kBaseSeccompPolicy, kExtraSeccompPolicy);
    if (!shengPreloadQtiProviders()) return 2;
    void* payload = dlopen(kShengQtiPayloadLibrary, RTLD_NOW | RTLD_LOCAL);
    if (!payload) {
        ALOGE("QTI service payload load failed: %s", dlerror());
        return 3;
    }
    const bool probe = argc == 2 && std::strcmp(argv[1], "--factory-probe") == 0;
    if (argc > 1 && !probe) return 4;
    if (probe) {
        using Entry = int (*)();
        auto entry = reinterpret_cast<Entry>(dlsym(payload, "sheng_qti_probe_entry"));
        if (!entry) return 5;
        std::setvbuf(stdout, nullptr, _IONBF, 0);
        std::puts("QTI_BOOTSTRAP: factory probe; no HAL registration; original seccomp enabled");
        return entry();
    }
    using Entry = int (*)(int, char**);
    auto entry = reinterpret_cast<Entry>(dlsym(payload, "sheng_qti_service_entry"));
    if (!entry) {
        ALOGE("QTI service payload entry unavailable: %s", dlerror());
        return 6;
    }
    return entry(argc, argv);
}
