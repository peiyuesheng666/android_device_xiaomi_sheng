#!/usr/bin/env bash
# Build the installed QTI module and the r60 configuration through normal Soong/Make.
set -euo pipefail
workspace=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd -P)
rom=${SHENG_ROM_ROOT:-/root/sheng-lineage/lineage-24.0}
review=${SHENG_REVIEW_ROOT:-/root/sheng-lineage/hardware-diagnostics/device-continue-20261112-build}
mkdir -p "$review"
run=$(mktemp -d "$review/r60-$(date -u +%Y%m%d-%H%M%S)-XXXXXX")
exec > >(tee "$run/build.log") 2>&1
printf 'Build evidence: %s\n' "$run"
completed=false
record_result() {
    result=$?
    python3 - "$run" "$result" "$completed" <<'PY'
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
work, result, completed = sys.argv[1:]
Path(work, 'status.json').write_text(json.dumps({
    'date_utc': datetime.now(timezone.utc).isoformat(), 'exit_code': int(result),
    'normal_module_build_passed': int(result) == 0 and completed == 'true',
    'postbuild_checks_completed': completed == 'true',
    'full_product_build_passed': False}, indent=2) + '\n')
PY
}
trap record_result EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
export SHENG_SOURCE_WORKSPACE="$workspace"
export SHENG_SOURCE_SCOPE='interfaces/compat/codec2 properties/vendor.prop rootdir/etc/init.sm8550.rc overlay/FrameworkResOverlaySheng sepolicy/vendor/genfs_contexts BoardConfig.mk device.mk'
export SHENG_BUILD_JOBS=${SHENG_BUILD_JOBS:-4} SHENG_STAGE_FACE_ENGINE=0
# Keep the installed r53 property date, avoiding unrelated build.prop changes.
export BUILD_DATETIME=${SHENG_BUILD_DATETIME:-1794387709}
export TZ=Asia/Singapore LANG=C.UTF-8 LC_ALL=C.UTF-8
cmp -- "$workspace/device/xiaomi/sheng/tools/postprocess_vendor.py" \
    "$rom/device/xiaomi/sheng/tools/postprocess_vendor.py"
# The non-installed source binary has no Make phony target. Its original vendor
# installer depends on that source output and performs the usual ELF check.
bash "$workspace/device/xiaomi/sheng/tools/build_hardware.sh" \
    vendor.qti.media.c2@1.0-service FrameworkResOverlaySheng init.sm8550.rc \
    librecovery_ui_sheng out/target/product/sheng/vendor/build.prop \
    selinux_policy vendor_file_contexts file_contexts.bin
mirror_args=()
read -r -a scopes <<< "$SHENG_SOURCE_SCOPE"
for scope in "${scopes[@]}"; do mirror_args+=(--path "$scope"); done
python3 "$workspace/device/xiaomi/sheng/tools/verify_device_source_mirror.py" \
    --workspace "$workspace" --rom "$rom" --output "$run/source-mirror.json" "${mirror_args[@]}"
python3 "$workspace/device/xiaomi/sheng/tools/audit_upstream_sources.py" --fetch \
    --output "$run/upstream-audit.json" > "$run/upstream-audit.log" 2>&1
completed=true
printf 'r60 normal module build and source checks passed: %s\n' "$run"
