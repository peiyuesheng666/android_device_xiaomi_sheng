// SPDX-License-Identifier: Apache-2.0
// Isolated diagnostic extension; the product bootstrap remains unchanged.
#define main sheng_factory_bootstrap_main
#include "../interfaces/compat/codec2/qti_bootstrap.cpp"
#undef main

int main(int argc, char** argv) {
    if (argc == 2 && std::strcmp(argv[1], "--factory-probe") == 0) {
        return sheng_factory_bootstrap_main(argc, argv);
    }
    if (argc != 5 || std::strcmp(argv[1], "--frame-probe") != 0) return 4;
    bool startupValid = true;
    dl_iterate_phdr(rejectStartupProviders, &startupValid);
    if (!startupValid) return 1;
    signal(SIGPIPE, SIG_IGN);
    android::SetUpMinijail("/vendor/etc/seccomp_policy/codec2.vendor.base-arm64.policy",
                          "/vendor/etc/seccomp_policy/codec2.vendor.ext-arm64.policy");
    if (!shengPreloadQtiProviders()) return 2;
    void* payload = dlopen("libsheng_qti_codec2_service.so", RTLD_NOW | RTLD_LOCAL);
    if (!payload) return 3;
    using Entry = int (*)(const char*, const char*, const char*);
    auto entry = reinterpret_cast<Entry>(dlsym(payload, "sheng_qti_frame_probe_entry"));
    if (!entry) return 5;
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    std::puts("QTI_FRAME_BOOTSTRAP: no HAL registration; original seccomp enabled");
    return entry(argv[2], argv[3], argv[4]);
}
