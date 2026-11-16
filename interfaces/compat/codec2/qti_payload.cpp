// SPDX-License-Identifier: Apache-2.0
// Use the reviewed factory and source-owned wrapper in the local payload group.
#define SHENG_QTI_SANDBOX_ALREADY_SET
#define main sheng_qti_payload_main
#include "qti_service.cpp"
#undef main

#include <cstdio>
#include <sys/prctl.h>

namespace {

bool sandboxReady() {
    const int noNewPrivileges = prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0);
    const int seccompMode = prctl(PR_GET_SECCOMP, 0, 0, 0, 0);
    if (noNewPrivileges != 1 || seccompMode != 2) {
        ALOGE("QTI payload requires the bootstrap sandbox: no_new_privs=%d seccomp=%d",
              noNewPrivileges, seccompMode);
        return false;
    }
    return true;
}
}  // namespace

extern "C" __attribute__((visibility("default")))
int sheng_qti_service_entry(int argc, char** argv) {
    if (!sandboxReady()) return 7;
    return sheng_qti_payload_main(argc, argv);
}

extern "C" __attribute__((visibility("default")))
int sheng_qti_probe_entry() {
    using android::hardware::media::c2::V1_0::utils::ComponentStore;
    if (!sandboxReady()) return 7;
    std::puts("QTI_PAYLOAD: no_new_privs=1 seccomp=2");
    android::ProcessState::initWithDriver("/dev/vndbinder");
    android::ProcessState::self()->startThreadPool();
    android::hardware::configureRpcThreadpool(8, false);
    auto implementation = getQtiComponentStore();
    if (!implementation) return 1;
    auto wrapper = makeQtiHidlStore(implementation);
    const auto status = wrapper->status();
    std::printf("QTI_PAYLOAD: platform_wrapper_size=%zu status=%d\n", sizeof(ComponentStore), status);
    if (status != C2_OK) return 2;
    auto components = implementation->listComponents();
    std::printf("QTI_PAYLOAD: store=%s component_count=%zu\n",
                implementation->getName().c_str(), components.size());
    if (components.size() != kShengQtiComponentCount) return 3;
    for (const auto& component : components) {
        if (!component || component->name.empty()) return 4;
        std::printf("QTI_PAYLOAD: component=%s type=%s kind=%d rank=%u\n",
                    component->name.c_str(), component->mediaType.c_str(),
                    static_cast<int>(component->kind), component->rank);
        std::shared_ptr<C2ComponentInterface> interface;
        const auto created = implementation->createInterface(component->name, &interface);
        std::printf("QTI_PAYLOAD: interface=%s status=%d available=%d\n",
                    component->name.c_str(), created, interface != nullptr);
        if (created != C2_OK || !interface) return 5;
        interface.reset();
    }
    std::printf("QTI_PAYLOAD: interface_create_release_count=%zu\n", components.size());
    // Interface construction does not allocate the actual vendor component.
    // Check the representative decoder and encoder implementations as well.
    // Do not start processing, register a HAL or touch secure playback here.
    for (const char* name : kShengQtiProbeComponents) {
        std::shared_ptr<C2Component> component;
        const auto created = implementation->createComponent(name, &component);
        std::printf("QTI_PAYLOAD: actual_component=%s status=%d available=%d\n",
                    name, created, component != nullptr);
        if (created != C2_OK || !component) return 6;
        auto interface = component->intf();
        if (!interface || interface->getName() != name) return 8;
        interface.reset();
        component.reset();
        std::printf("QTI_PAYLOAD: actual_component_released=%s\n", name);
    }
    std::printf("QTI_PAYLOAD: component_create_release_count=%zu\n",
                sizeof(kShengQtiProbeComponents) / sizeof(kShengQtiProbeComponents[0]));
    components.clear();
    wrapper.clear();
    implementation.reset();
    std::puts("QTI_PAYLOAD: wrapper and store released; natural process teardown pending");
    return 0;
}
