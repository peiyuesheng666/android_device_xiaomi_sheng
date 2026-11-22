/* SPDX-License-Identifier: Apache-2.0
 * Inspect vendor display library loading and its capability factory in isolation.
 * No display, framebuffer, brightness or mode-setting interface is called.
 */
#include <dlfcn.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IONBF, 0);
    if (argc != 2 || (strcmp(argv[1], "--inspect-capabilities")
            && strcmp(argv[1], "--inspect-libraries"))) return 2;
    /* These vendor plugins register process-lifetime callbacks. Keep their
     * mappings alive until this short-lived diagnostic process exits.
     */
    const char *libraries[] = {"libhdr_tm.so", "libhdrdynamic.so", "libhdrdynamicootf.so",
                              "libhdrvivid.so", "libhdr_hbm.so", "libhdr_backlight_adapter.so"};
    for (unsigned i = 0; i < sizeof(libraries) / sizeof(libraries[0]); ++i) {
        void *handle = dlopen(libraries[i], RTLD_NOW | RTLD_LOCAL);
        const char *error = handle ? "" : dlerror();
        printf("DISPLAY_LIBRARY name=%s loaded=%d error=%s\n", libraries[i], handle != NULL,
               error ? error : "unknown");
    }
    if (!strcmp(argv[1], "--inspect-libraries")) return 0;
    void *library = dlopen("libsdmextension.so", RTLD_NOW | RTLD_LOCAL);
    if (!library) { fprintf(stderr, "Display extension load failed: %s\n", dlerror()); return 1; }
    /* The inspected stock library exports these typed C++ methods. The runner
     * records that library's identity; this diagnostic is not a production ABI.
     */
    int (*create)(void **) = (int (*)(void **))dlsym(library, "_ZN3sdm16CapabilitiesImpl6CreateEPPS0_");
    int (*query)(void *, int, bool *) = (int (*)(void *, int, bool *))dlsym(library,
            "_ZN3sdm16CapabilitiesImpl13GetCapabilityENS_17FeatureCapabilityEPb");
    int (*destroy)(void *) = (int (*)(void *))dlsym(library, "_ZN3sdm16CapabilitiesImpl7DestroyEPS0_");
    if (!create || !query || !destroy) {
        fprintf(stderr, "Display capability exports are unavailable\n");
        return 1;
    }
    void *capabilities = NULL;
    int status = create(&capabilities);
    printf("DISPLAY_CAPABILITY factory_status=%d object_created=%d\n", status, capabilities != NULL);
    if (!status && capabilities) {
        const char *features[] = {"hdr10", "hdr10plus", "dolby_vision"};
        for (int feature = 0; feature < 3; ++feature) {
            bool supported = false;
            int result = query(capabilities, feature, &supported);
            printf("DISPLAY_CAPABILITY feature=%s status=%d supported=%d\n", features[feature], result, supported);
        }
        printf("DISPLAY_CAPABILITY destroy_status=%d\n", destroy(capabilities));
    }
    return 0;
}
