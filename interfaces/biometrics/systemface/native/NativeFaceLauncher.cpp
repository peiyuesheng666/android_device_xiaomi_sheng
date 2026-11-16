/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 *
 * Runtime lifecycle follows the manifest-pinned AOSP app_process AppRuntime
 * (frameworks/base 696a5773fa284f53429dbb6c3e5dcc96bf5bd0b3).
 * This init-owned HAL executable has no general command-line JVM/class launcher.
 */
#define LOG_TAG "ShengNativeFace"
#include <android_runtime/AndroidRuntime.h>
#include <binder/IPCThreadState.h>
#include <binder/ProcessState.h>
#include <utils/Log.h>
#include <cstring>
#include <sys/stat.h>
#include <unistd.h>

namespace {
constexpr const char* kMain = "org.lineageos.sheng.face.NativeFaceMain";
class FaceRuntime final : public android::AndroidRuntime {
  public:
    FaceRuntime(char* args, size_t length, bool test)
        : AndroidRuntime(args, length) {
        if (test) arguments_.add(android::String8("--self-test"));
    }
    void onVmCreated(JNIEnv* env) override {
        // Resolve the non-boot class before RuntimeInit changes the JNI caller's
        // classloader, as the pinned AOSP AppRuntime does. AndroidRuntime's
        // findClass declaration has no exported implementation.
        jclass local = env->FindClass("org/lineageos/sheng/face/NativeFaceMain");
        LOG_ALWAYS_FATAL_IF(local == nullptr, "Native Face bootstrap class missing");
        main_ = reinterpret_cast<jclass>(env->NewGlobalRef(local));
        env->DeleteLocalRef(local);
        LOG_ALWAYS_FATAL_IF(main_ == nullptr, "Native Face bootstrap reference failed");
    }
    void onStarted() override {
        android::ProcessState::self()->startThreadPool();
        callMain(android::String8(kMain), main_, arguments_);
        android::IPCThreadState::self()->stopProcess();
    }
  private:
    jclass main_ = nullptr;
    android::Vector<android::String8> arguments_;
};
}

int main(int argc, char* argv[]) {
    if (getuid() != 1000 || (argc != 1 &&
            (argc != 2 || std::strcmp(argv[1], "--self-test") != 0))) {
        ALOGE("Init system UID and fixed service/self-test mode required");
        return 1;
    }
    umask(0077);
    FaceRuntime runtime(argv[0], std::strlen(argv[0]) + 1, argc == 2);
    runtime.addOption("-Djava.class.path=/system_ext/framework/ShengNativeFaceBootstrap.jar");
    // No compiler child can be executed from this HAL domain. ART uses immutable
    // system boot artifacts and interprets packaged DEX. The platform's
    // neverallow forbids executable writable tmpfs for this HAL domain.
    runtime.addOption("-Xnoimage-dex2oat");
    runtime.addOption("-Xusejit:false");
    android::Vector<android::String8> options;
    options.add(android::String8("application"));
    runtime.start("com.android.internal.os.RuntimeInit", options, false);
    return 0;
}
