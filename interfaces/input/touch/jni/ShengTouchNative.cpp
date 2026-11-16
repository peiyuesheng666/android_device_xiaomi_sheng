// SPDX-License-Identifier: Apache-2.0
#include "TouchControl.h"

#include <atomic>
#include <jni.h>

namespace {
std::atomic<jlong> generation{0};
bool cancelled(void* context) {
    return generation.load() != *static_cast<const jlong*>(context);
}
}  // namespace

extern "C" JNIEXPORT jlong JNICALL
Java_com_xiaomi_sheng_touch_ShengTouchApplication_nativeInvalidate(JNIEnv*, jclass) {
    return generation.fetch_add(1) + 1;
}

extern "C" JNIEXPORT jint JNICALL
Java_com_xiaomi_sheng_touch_ShengTouchApplication_nativeApply(
        JNIEnv*, jclass, jint desired, jlong expectedGeneration) {
    auto io = sheng::touch::makePosixIo();
    return sheng::touch::apply(*io, desired, cancelled, &expectedGeneration);
}
