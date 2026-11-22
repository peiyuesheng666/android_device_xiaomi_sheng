#!/usr/bin/env bash
set -euo pipefail
workspace=/mnt/c/Users/Dev裴月笙/Desktop/XiaomiPad6SProPort6.18
review=/root/sheng-lineage/hardware-diagnostics/sheng-accessories-r53-20261111
export SHENG_SOURCE_WORKSPACE="$workspace"
export SHENG_SOURCE_SCOPE='BoardConfig.mk interfaces/input/keyboard'
export SHENG_BUILD_JOBS=4 BUILD_DATETIME=1794387709
export TZ=Asia/Singapore LANG=C.UTF-8 LC_ALL=C.UTF-8
bash "$workspace/device/xiaomi/sheng/tools/build_hardware.sh" \
    ShengKeyboardPresence init.sheng-keyboard-presence.rc vendor_file_contexts selinux_policy file_contexts.bin \
    2>&1 | tee "$review/build.log"
python3 "$workspace/device/xiaomi/sheng/tools/verify_device_source_mirror.py" \
    --workspace "$workspace" --rom /root/sheng-lineage/lineage-24.0 \
    --path BoardConfig.mk --path interfaces/input/keyboard --output "$review/final-source-mirror.json"
python3 "$workspace/device/xiaomi/sheng/tools/audit_upstream_sources.py" --fetch \
    --output "$review/postbuild-upstream-audit.json" > "$review/postbuild-upstream-audit.log" 2>&1
