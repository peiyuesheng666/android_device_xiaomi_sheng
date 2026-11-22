# SPDX-License-Identifier: Apache-2.0
# Fail the debug product build on upstream drift or edited pinned copies.
# This gate only reads/compares source and never patches a public repository.
ifeq ($(TARGET_DEVICE),sheng)
ifneq ($(filter userdebug eng,$(TARGET_BUILD_VARIANT)),)
ifeq ($(SOONG_CONFIG_sheng_first_stage_rootfix),true)
_sheng_first_stage_source_check := $(shell python3 device/xiaomi/sheng/diagnostics/magisk-overlay-rootfix/materialize_source_variants.py --rom . --device device/xiaomi/sheng --check-only 2>&1)
ifneq ($(_sheng_first_stage_source_check),SHENG_SOURCE_VARIANTS_VERIFIED)
$(error sheng first-stage source verification failed: $(_sheng_first_stage_source_check))
endif
endif
endif
endif
