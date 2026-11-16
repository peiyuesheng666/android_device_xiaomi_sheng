# SPDX-License-Identifier: Apache-2.0
# Device applications in product use platform input and hardware APIs.
override PRODUCT_ENFORCE_PRODUCT_PARTITION_INTERFACE := false
PRODUCT_NOT_DEBUGGABLE_IN_USERDEBUG := false

# Enable USB debugging for the requested tablet bring-up, with RSA authorization.
ifneq ($(filter userdebug eng,$(TARGET_BUILD_VARIANT)),)
PRODUCT_COPY_FILES += \
    device/xiaomi/sheng/rootdir/etc/init.sheng.debug-adb.rc:$(TARGET_COPY_OUT_SYSTEM)/etc/init/init.sheng.debug-adb.rc
endif

PRODUCT_DEVICE := sheng
PRODUCT_BRAND := Xiaomi
PRODUCT_MANUFACTURER := Xiaomi
# Keep the supplied firmware's CN hardware identifier in both products.
PRODUCT_MODEL := 24018RPACC
PRODUCT_MARKETNAME := Xiaomi Pad 6S Pro 12.4
PRODUCT_GMS_CLIENTID_BASE := android-xiaomi
