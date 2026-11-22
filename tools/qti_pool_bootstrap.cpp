// SPDX-License-Identifier: Apache-2.0
// Isolated service-lifetime diagnostic; not installed in the product.
#define main sheng_factory_bootstrap_main
#include "../interfaces/compat/codec2/qti_bootstrap.cpp"
#undef main

int main(int argc, char** argv) {
    if (argc == 2 && std::strcmp(argv[1], "--factory-probe") == 0) {
        return sheng_factory_bootstrap_main(argc, argv);
    }
    if (argc != 2 || std::strcmp(argv[1], "--pool-probe") != 0) return 4;
    bool startupValid = true;
    dl_iterate_phdr(rejectStartupProviders, &startupValid);
    if (!startupValid) return 1;
    signal(SIGPIPE, SIG_IGN);
    android::SetUpMinijail(kBaseSeccompPolicy, kExtraSeccompPolicy);
    if (!shengPreloadQtiProviders()) return 2;
    void* payload = dlopen(kShengQtiPayloadLibrary, RTLD_NOW | RTLD_LOCAL);
    if (!payload) return 3;
    using Entry = int (*)();
    auto entry = reinterpret_cast<Entry>(dlsym(payload, "sheng_qti_pool_probe_entry"));
    if (!entry) return 5;
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    std::puts("QTI_POOL_BOOTSTRAP: no HAL registration; original seccomp enabled");
    return entry();
}
