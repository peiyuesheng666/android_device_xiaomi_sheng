# SPDX-License-Identifier: Apache-2.0
$(call soong_config_set, sheng, rom, lineage)
# Match BoardConfig's arm64-only userspace and the ART APEX compiler payload.
$(call inherit-product, $(SRC_TARGET_DIR)/product/core_64_bit_only.mk)
$(call inherit-product, $(SRC_TARGET_DIR)/product/full_base.mk)
$(call inherit-product, device/xiaomi/sheng/device.mk)
TARGET_EXCLUDES_AUDIOFX := true
$(call inherit-product, vendor/lineage/config/common_full_tablet_wifionly.mk)

# Apply identity and policy to this product rather than inheriting base defaults.
include device/xiaomi/sheng/product-common.mk
PRODUCT_NAME := lineage_sheng
