#!/usr/bin/env bash
# Normal property target; public source is audited by the existing build harness.
set -euo pipefail
workspace=${SHENG_SOURCE_WORKSPACE:?Set the authoritative workspace}
rom=/root/sheng-lineage/lineage-24.0
review=/root/sheng-lineage/hardware-diagnostics/sheng-dolby-media-r52-20261111
mkdir -p "$review"
export SHENG_SOURCE_SCOPE=properties/vendor.prop
export SHENG_BUILD_JOBS=4
# Retain the installed vendor build date for a narrow configuration update.
export BUILD_DATETIME=1794387709
export TZ=Asia/Singapore LANG=C.UTF-8 LC_ALL=C.UTF-8
bash "$workspace/device/xiaomi/sheng/tools/build_hardware.sh" \
    out/target/product/sheng/vendor/build.prop 2>&1 | tee "$review/build.log"
python3 "$workspace/device/xiaomi/sheng/tools/verify_device_source_mirror.py" \
    --workspace "$workspace" --rom "$rom" --path properties/vendor.prop \
    --output "$review/final-source-mirror.json"
python3 "$workspace/device/xiaomi/sheng/tools/audit_upstream_sources.py" --fetch \
    --output "$review/postbuild-upstream-audit.json" > "$review/postbuild-upstream-audit.log" 2>&1
