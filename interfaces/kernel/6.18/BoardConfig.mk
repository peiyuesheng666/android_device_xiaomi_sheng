# Compile the kernel through the ROM's standard source-kernel rules.
TARGET_KERNEL_SOURCE := kernel/xiaomi/sheng
TARGET_KERNEL_CONFIG := sheng_defconfig
TARGET_KERNEL_CONFIG_EXT :=
TARGET_FORCE_PREBUILT_KERNEL :=
TARGET_PREBUILT_KERNEL :=
TARGET_KERNEL_EXT_MODULE_ROOT := $(DEVICE_PATH)/interfaces/kernel/6.18
TARGET_KERNEL_EXT_MODULES := android-modules

SHENG_KERNEL_PROJECT := $(abspath kernel/xiaomi/sheng-build)
SHENG_KERNEL_DEPS ?= $(abspath ../diagnostics/kernel618-android-deps)
SHENG_KERNEL_PREBUILTS := $(SHENG_KERNEL_DEPS)/prebuilts
TARGET_KERNEL_CLANG_PATH := $(SHENG_KERNEL_PREBUILTS)/clang/host/linux-x86/clang-r584948c
TARGET_KERNEL_LIBCLANG_PATH := $(TARGET_KERNEL_CLANG_PATH)/lib
TARGET_KERNEL_RUST_VERSION := 1.91.1.p3
TARGET_KERNEL_LIBC_SYSROOT_USE := host
TARGET_KERNEL_CLANG_AUTOFDO_PROFILE := none
TARGET_KERNEL_ADDITIONAL_FLAGS := -j4 \
    HOSTCFLAGS="-O2 -I$(SHENG_KERNEL_DEPS)/elfutils-0.193/include" \
    HOSTLDFLAGS="-L$(SHENG_KERNEL_DEPS)/elfutils-0.193/lib -Wl,-rpath,$(SHENG_KERNEL_DEPS)/elfutils-0.193/lib" \
    RUSTC=$(SHENG_KERNEL_PREBUILTS)/rust-toolchain/linux-x86/1.91.1.p3/bin/rustc \
    RUST_LIB_SRC=$(SHENG_KERNEL_PREBUILTS)/rust-toolchain/linux-x86/1.91.1.p3/lib/rustlib/src/rust/library \
    RUSTC_BOOTSTRAP=1 BINDGEN=$(SHENG_KERNEL_PREBUILTS)/clang-tools/linux-x86/bin/bindgen \
    PAHOLE=$(SHENG_KERNEL_PREBUILTS)/kernel-build-tools/linux_musl-x86/bin/pahole \
    KBUILD_GENDWARFKSYMS_STABLE=1 LOCALVERSION=
BOARD_KERNEL_CMDLINE += sched_proxy_exec=0
# build/make appends these after INTERNAL_RECOVERYIMAGE_ARGS. mkbootimg's last
# --cmdline wins, including for a kernel-less Recovery sharing the boot kernel.
# Recursive expansion retains the final common boot arguments without changing
# normal Android's default-enabled boot-only logger or adding a reset deadline.
BOARD_RECOVERY_MKBOOTIMG_ARGS = $(BOARD_MKBOOTIMG_ARGS) --cmdline "$(INTERNAL_KERNEL_CMDLINE) sheng_bootlog.enable=0 sheng_bootlog.test_timeout=0"
BOOT_KERNEL_MODULES :=
RECOVERY_KERNEL_MODULES :=
BOOT_KERNEL_MODULES_FINDER := $(DEVICE_PATH)/tools/find_sheng_source_boot_modules.py
RECOVERY_KERNEL_MODULES_FINDER := $(DEVICE_PATH)/tools/find_sheng_source_recovery_modules.py
BOARD_VENDOR_KERNEL_MODULES_LOAD := $(strip $(shell cat $(DEVICE_PATH)/configs/modules/source-kernel/vendor.load))
BOARD_VENDOR_RAMDISK_KERNEL_MODULES_LOAD := $(strip $(shell cat $(DEVICE_PATH)/configs/modules/source-kernel/first_stage.load))
BOARD_VENDOR_RAMDISK_RECOVERY_KERNEL_MODULES_LOAD := $(strip $(shell cat $(DEVICE_PATH)/configs/modules/source-kernel/recovery.load))
BOARD_RECOVERY_KERNEL_MODULES_LOAD := $(BOARD_VENDOR_RAMDISK_RECOVERY_KERNEL_MODULES_LOAD)

# Export the selected BSP UAPI groups through the sandboxed kernel generator.
# Explicit variant exclusions preserve the selected drivers and core kernel ABI.
$(call soong_config_set,lineageKernelHeaders,additional_uapi_dirs,$(strip $(shell cat $(DEVICE_PATH)/interfaces/kernel/6.18/uapi-roots.list)))
$(call soong_config_set,lineageKernelHeaders,excluded_uapi_files,$(strip $(shell cat $(DEVICE_PATH)/interfaces/kernel/6.18/uapi-excludes.list)))
