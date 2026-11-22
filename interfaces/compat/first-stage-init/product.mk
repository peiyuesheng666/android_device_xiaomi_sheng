# SPDX-License-Identifier: Apache-2.0
# Match the debug-only remounter's qualification scope. User builds unchanged.
PRODUCT_PACKAGES_DEBUG += init_first_stage
# Explicit false on user products prevents any stale/configured debug selection.
$(call soong_config_set,sheng,first_stage_rootfix,$(if $(filter userdebug eng,$(TARGET_BUILD_VARIANT)),true,false))
