# SPDX-License-Identifier: Apache-2.0
$(call soong_config_set, sheng, rom, pixelos)
$(call inherit-product, $(SRC_TARGET_DIR)/product/core_64_bit_only.mk)
$(call inherit-product, $(SRC_TARGET_DIR)/product/full_base.mk)

TARGET_EXCLUDES_AUDIOFX := true
TARGET_SCREEN_WIDTH := 3048
TARGET_SCREEN_HEIGHT := 2032
$(call inherit-product, vendor/custom/config/common_full_tablet_wifionly.mk)

$(call inherit-product, device/xiaomi/sheng/device.mk)

# Match the permissions requested by PixelOS's prebuilt product Clock.
PRODUCT_COPY_FILES += \
    device/xiaomi/sheng/configs/permissions/privapp-permissions-sheng-pixelos.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/permissions/privapp-permissions-sheng-pixelos.xml

# Pixel product overlays otherwise supersede the board's ODM attention choice.
PRODUCT_PACKAGES += ShengAttentionOverlay

# Match Sense enrollment's camera preview to this tablet's natural landscape.
PRODUCT_PACKAGES += ParanoidSenseResOverlaySheng

# Apply identity and policy to this product rather than inheriting base defaults.
include device/xiaomi/sheng/product-common.mk
PRODUCT_NAME := custom_sheng
