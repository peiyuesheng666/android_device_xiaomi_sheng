# SPDX-License-Identifier: Apache-2.0
LOCAL_PATH := $(call my-dir)

# The nested kernel build can validate an unchanged Image after Kconfig or
# module packaging inputs change. Let Ninja restat this output after success.
ifeq ($(TARGET_DEVICE),sheng)
# Lineage handles "out" and absolute OUT_DIR values, but a named relative
# output directory also needs the Android root after nested make changes cwd.
# Set this for Make tasks here; Soong keeps its own sandbox-relative paths.
KERNEL_BUILD_OUT_PREFIX := $(if $(filter /%,$(OUT_DIR)),,$(abspath .)/)
.KATI_RESTAT: $(TARGET_OUT_INTERMEDIATES)/KERNEL_OBJ/arch/$(if $(TARGET_KERNEL_ARCH),$(TARGET_KERNEL_ARCH),$(TARGET_ARCH))/boot/$(BOARD_KERNEL_IMAGE_NAME)
endif

include $(call all-makefiles-under,$(LOCAL_PATH))
