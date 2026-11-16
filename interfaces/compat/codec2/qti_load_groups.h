// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <dlfcn.h>
#include <log/log.h>

// Each provider is a separate RTLD_LOCAL root. Its own field definitions then
// precede its dependencies during relocation. Keep V4L2 before colorconvert:
// colorconvert can otherwise cause V4L2 to bind to its fields.
inline constexpr const char* kShengQtiProviderLibraries[] = {
#if defined(SHENG_QTI_AUDIO)
    "libcodec2_vndk.so",
    // Audio has one additional field-vector provider. Isolate it before loading
    // the registry and retain its two codec plugins through process teardown.
    "libqc2audio_basecodec.so",
    "libqc2audio_swaudiocodec.so",
    "libqc2audio_hwaudiocodec.so",
#else
    "libcodec2_vndk.so",
    "libqcodec2_v4l2codec.so",
    "libqcodec2_filterbase.so",
    "libqc2audio_basecodec.so",
    "libqc2filter.so",
    "libqc2colorconvertfilter.so",
    "libqc2vppfilter.so",
    // OEM registry teardown closes these plugins before all C2 objects that
    // refer to their vtables have been finalized. Retain ordinary references
    // to keep their code/data mapped while those finalizers run.
    "libqcodec2_imgtxrfilter.so",
    "libqcodec2_cvpfilter.so",
#endif
};

inline bool shengPreloadQtiProviders() {
    // Code and callbacks can outlive service registration. Keep the references
    // for the process lifetime; all ordinary finalizers still run at exit.
    static void* handles[sizeof(kShengQtiProviderLibraries) /
                         sizeof(kShengQtiProviderLibraries[0])]{};
    for (size_t i = 0; i < sizeof(handles) / sizeof(handles[0]); ++i) {
        handles[i] = dlopen(kShengQtiProviderLibraries[i], RTLD_NOW | RTLD_LOCAL);
        if (!handles[i]) {
            ALOGE("QTI provider load failed: %s: %s", kShengQtiProviderLibraries[i], dlerror());
            return false;
        }
    }
    return true;
}
