#!/usr/bin/env bash
# Normal module builds without the general builder's deferred face staging.
set -euo pipefail
workspace=/mnt/c/Users/Dev裴月笙/Desktop/XiaomiPad6SProPort6.18
rom=/root/sheng-lineage/lineage-24.0
review=/root/sheng-lineage/hardware-diagnostics/sheng-pen-settings-20261112
qti_build=${SHENG_QTI_BOOTSTRAP_BUILD:-}
qti_runtime=${SHENG_QTI_BOOTSTRAP_RUNTIME:-}
if [[ -n "$qti_build" || -n "$qti_runtime" ]]; then
    if [[ -z "$qti_build" || -z "$qti_runtime" || ${SHENG_INCLUDE_MEDIA_SENSORS:-0} != 1 ]]; then
        echo 'QTI selection requires both qualified receipt directories and media source verification' >&2
        exit 2
    fi
    if [[ ! -f "$qti_build/build.json" || ! -f "$qti_runtime/runtime.json" ]]; then
        echo 'QTI build/runtime receipts are missing' >&2
        exit 2
    fi
fi
mkdir -p "$review"
run=$(mktemp -d "$review/modules-$(date -u +%Y%m%d-%H%M%S)-XXXXXX")
modules=("$@")
if (( ${#modules[@]} == 0 )); then modules=(ShengPenSettings librecovery_ui_sheng); fi
# Leave memory for the WSL host and Ninja. A 24 GiB Go limit exhausted the
# 20 GiB guest and the Windows commit reserve before analysis completed.
memory_limit=${SHENG_SOONG_GOMEMLIMIT:-12GiB}
cpu_limit=${SHENG_SOONG_CPU_LIMIT:-4}
build_jobs=${SHENG_BUILD_JOBS:-4}
[[ "$memory_limit" =~ ^[1-9][0-9]*GiB$ && "$cpu_limit" =~ ^[1-9][0-9]*$ ]]
[[ "$build_jobs" =~ ^[1-9][0-9]*$ && "$build_jobs" -le 24 ]]
for module in "${modules[@]}"; do
    [[ "$module" =~ ^[A-Za-z0-9_][-A-Za-z0-9_./@+]*$ && "/$module/" != *'/../'* ]]
done
exec > >(tee "$run/build.log") 2>&1
printf 'Build evidence: %s\n' "$run"
builder="$rom/out/host/linux-x86/bin/soong_build"
real_builder="$builder.sheng-real"
phase=preflight
completed=false
cleanup() {
    result=$?
    if [[ ${owns_wrapper:-false} == true && -f "$real_builder" ]]; then
        mv -f -- "$real_builder" "$builder"
    fi
    python3 - "$run" "$result" "$phase" "$memory_limit" "$build_jobs" "$completed" "${modules[@]}" <<'PY'
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
work, result, phase, memory, jobs, completed, *modules = sys.argv[1:]
Path(work, 'status.json').write_text(json.dumps({
    'date_utc': datetime.now(timezone.utc).isoformat(), 'exit_code': int(result),
    'last_phase': phase, 'modules': modules, 'soong_gomemlimit': memory,
    'build_jobs': int(jobs),
    'normal_module_build_passed': int(result) == 0 and completed == 'true',
    'postbuild_checks_completed': completed == 'true',
    'full_product_build_passed': False}, indent=2) + '\n')
PY
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 141' PIPE
cd "$rom"
exec 9>out/.sheng-device-modules.lock
flock -n 9 || { echo 'Another device module build owns the output lock' >&2; exit 1; }
if [[ -f "$real_builder" ]] || pgrep -f '^.*/soong_build( |$)' > /dev/null; then
    echo 'Another build owns the Soong analyzer; refusing to overlap' >&2
    exit 1
fi
# Only existing swap files in the registered C-backed WSL distro are allowed.
python3 "$workspace/device/xiaomi/sheng/tools/prepare_sheng_stylus_swap.py" --work "$run"
free -h
phase=source-audit
python3 "$workspace/device/xiaomi/sheng/tools/audit_upstream_sources.py" --fetch \
    --output "$run/prebuild-upstream-audit.json" > "$run/prebuild-upstream-audit.log" 2>&1
# These Recovery dependencies are outside the general hardware audit's list.
python3 - "$workspace" "$rom" "$run" <<'PY'
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

workspace, rom, output = map(Path, sys.argv[1:])
sys.path.insert(0, str(workspace / 'device/xiaomi/sheng/tools'))
from audit_upstream_sources import inspect

repositories = ['bootable/recovery', 'system/core', 'build/make', 'vendor/lineage']
with ThreadPoolExecutor(max_workers=4) as executor:
    results = list(executor.map(lambda path: inspect(rom, path, True), repositories))
passed = all(result['passed'] for result in results)
(output / 'prebuild-recovery-upstream-audit.json').write_text(json.dumps({
    'date_utc': datetime.now(timezone.utc).isoformat(), 'repositories': results,
    'passed': passed}, indent=2) + '\n')
print(f'Recovery build dependency audit: {len(results)} repositories, passed={passed}')
if not passed:
    raise SystemExit(1)
PY
phase=source-sync
prepare_args=()
mirror_args=()
if [[ ${SHENG_INCLUDE_MEDIA_SENSORS:-0} == 1 ]]; then
    prepare_args+=(--include-media-sensors)
    mirror_args+=(--path interfaces/compat/codec2/Android.bp
                 --path interfaces/compat/codec2/qti_service.cpp
                 --path interfaces/compat/codec2/qti_bootstrap.cpp
                 --path interfaces/compat/codec2/qti_payload.cpp
                 --path interfaces/compat/codec2/qti_load_groups.h
                 --path interfaces/compat/codec2/qti_profile.h
                 --path properties/vendor.prop
                 --path overlay/FrameworkResOverlaySheng/res/values/platform-defaults.xml
                 --path rootdir/etc/init.sm8550.rc
                 --path sepolicy/vendor/genfs_contexts)
fi
if [[ -n "$qti_build" ]]; then
    prepare_args+=(--qti-bootstrap-build "$qti_build" --qti-bootstrap-runtime "$qti_runtime"
                  --build-lock-fd 9)
fi
python3 "$workspace/device/xiaomi/sheng/tools/prepare_sheng_pen_settings_product.py" \
    --work "$run" --include-recovery "${prepare_args[@]}"
python3 "$workspace/device/xiaomi/sheng/tools/audit_sheng_product_apps.py" \
    --device "$rom/device/xiaomi/sheng" --reference-device "$workspace/device/xiaomi/sheng" \
    --output "$run/product-apps.json"
export TZ=Asia/Singapore LANG=C.UTF-8 LC_ALL=C.UTF-8
phase=product-configuration
# Product configuration also invokes Go tools before the sanitized analyzer.
export GOMEMLIMIT="$memory_limit" GOGC=40
source build/envsetup.sh
lunch lineage_sheng-cp2a-userdebug
[[ "$(get_build_var PRODUCT_ENFORCE_PRODUCT_PARTITION_INTERFACE)" == false ]] || {
    echo 'Device product applications require the configured platform API access' >&2; exit 1;
}
export USE_CCACHE=1 CCACHE_EXEC=/usr/bin/ccache
export CCACHE_DIR=/root/sheng-lineage/ccache CCACHE_COMPRESS=true
export SOONG_ALLOW_MISSING_DEPENDENCIES=false SOONG_NINJA=ninja NINJA_HIGHMEM_NUM_JOBS=2
# The combined graph defines highmem_pool before including the Soong graph.
# Parsing that included graph alone incorrectly rejects valid high-memory rules.
graph=out/combined-lineage_sheng.ninja
if [[ -f "$graph" ]] && ! prebuilts/build-tools/linux-x86/bin/ninja -f "$graph" \
    -t targets depth 1 > /dev/null 2> "$run/prior-graph-parse.log"; then
    # Preserve the incomplete output and let normal Soong regenerate it.
    mv -- "$graph" "$run/combined-lineage_sheng.ninja.incomplete"
    echo 'Preserved the invalid prior Ninja graph; regenerating with Soong'
fi
# Repo keeps JSON caches beside Git configs, including the read-only home and
# checkout paths seen by Ninja's sandbox. Populate them before entering it.
phase=manifest-cache-warmup
REPO_TRACE=0 python3 .repo/repo/repo manifest -o "$run/manifest-cache-warmup.xml" -r \
    > "$run/manifest-cache-warmup.log" 2>&1
phase=bootstrap
if [[ -f out/soong/bootstrap.ninja ]]; then
    prebuilts/build-tools/linux-x86/bin/ninja -f out/soong/bootstrap.ninja out/host/linux-x86/bin/soong_build
fi
if [[ -f "$builder" ]]; then
    build_cpus=$(python3 - "$cpu_limit" <<'PY'
import os
import sys
print(','.join(map(str, sorted(os.sched_getaffinity(0))[:int(sys.argv[1])])))
PY
)
    mv -- "$builder" "$real_builder"
    owns_wrapper=true
    # Soong sanitizes the invocation's environment. Change only its generated
    # executable, restoring it when the build exits.
    printf '#!/bin/sh\nexport GOMEMLIMIT=%s GOGC=40\nexec /usr/bin/taskset -c "%s" "%s" "$@"\n' \
        "$memory_limit" "$build_cpus" "$real_builder" > "$builder"
    chmod 755 "$builder"
    touch -r "$real_builder" "$builder"
fi
phase=module-build
m -j"$build_jobs" "${modules[@]}"
phase=source-verification
python3 "$workspace/device/xiaomi/sheng/tools/verify_device_source_mirror.py" \
    --workspace "$workspace" --rom "$rom" --path interfaces/input/pen \
    --path Android.bp --path Android.mk --path configs/touch/sheng-touch-report \
    --path rootdir/recovery --path rootdir/etc/init.recovery.qcom.rc --path proprietary-files.txt \
    --path sepolicy/vendor/file.te --path sepolicy/vendor/init.te --path sepolicy/vendor/genfs_contexts \
    --path configs/modules/modules.list.boot --path configs/modules/modules.load.first_stage \
    --path configs/modules/modules.list.recovery --path configs/modules/modules.load.recovery \
    --reject-extra --output "$run/source-mirror.json" "${mirror_args[@]}"
if [[ ${SHENG_INCLUDE_MEDIA_SENSORS:-0} == 1 ]]; then
    cmp -- "$workspace/device/xiaomi/sheng/tools/postprocess_vendor.py" \
        "$rom/device/xiaomi/sheng/tools/postprocess_vendor.py"
fi
if [[ " ${modules[*]} " == *' ShengPenSettings '* ]]; then
    sha256sum out/target/product/sheng/product/app/ShengPenSettings/ShengPenSettings.apk > "$run/apk.sha256"
fi
phase=postbuild-audit
python3 "$workspace/device/xiaomi/sheng/tools/audit_upstream_sources.py" --fetch \
    --output "$run/postbuild-upstream-audit.json" > "$run/postbuild-upstream-audit.log" 2>&1
phase=complete
completed=true
