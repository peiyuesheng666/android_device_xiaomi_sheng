# SPDX-License-Identifier: Apache-2.0
# Match the upstream remounter and its policy's userdebug_or_eng lifetime.
# The normal user build must not gain a second overlay-remount implementation.
PRODUCT_PACKAGES_DEBUG += overlay_remounter
