// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <cstddef>

#if defined(SHENG_QTI_AUDIO)
inline constexpr char kLibrary[] = "libqc2audio_core.so";
inline constexpr char kFactoryGetter[] = "QC2AudioComponentStoreFactoryGetter";
inline constexpr char kBaseSeccompPolicy[] =
        "/vendor/etc/seccomp_policy/c2audio.vendor.base-arm64.policy";
inline constexpr char kExtraSeccompPolicy[] =
        "/vendor/etc/seccomp_policy/c2audio.vendor.ext-arm64.policy";
inline constexpr char kShengQtiPayloadLibrary[] = "libsheng_qti_audio_codec2_service.so";
inline constexpr char kShengQtiProcessName[] = "media.audio.qc.codec";
inline constexpr char kShengQtiInstance[] = "default2";
inline constexpr size_t kShengQtiComponentCount = 17;
inline constexpr const char* kShengQtiProbeComponents[] = {
    "c2.qti.flac.sw.decoder", "c2.qti.aac.hw.decoder", "c2.qti.aac.hw.encoder",
    "c2.qti.alac.sw.decoder", "c2.qti.alac.hw.decoder",
};
#else
inline constexpr char kLibrary[] = "libqcodec2_core.so";
inline constexpr char kFactoryGetter[] = "QC2ComponentStoreFactoryGetter";
inline constexpr char kBaseSeccompPolicy[] =
        "/vendor/etc/seccomp_policy/codec2.vendor.base-arm64.policy";
inline constexpr char kExtraSeccompPolicy[] =
        "/vendor/etc/seccomp_policy/codec2.vendor.ext-arm64.policy";
inline constexpr char kShengQtiPayloadLibrary[] = "libsheng_qti_codec2_service.so";
inline constexpr char kShengQtiProcessName[] = "media.hwcodec";
inline constexpr char kShengQtiInstance[] = "default";
inline constexpr size_t kShengQtiComponentCount = 19;
inline constexpr const char* kShengQtiProbeComponents[] = {
    "c2.qti.avc.decoder", "c2.qti.hevc.encoder",
};
#endif
