#!/usr/bin/env bash
# Build the device-owned hardware modules and stage scoped Settings integration.
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
rom=${SHENG_ROM_ROOT:-$(realpath "$here/../../../..")}
cd "$rom"
rom=$(pwd -P)
[[ -f build/envsetup.sh ]] || { echo 'Set SHENG_ROM_ROOT to the synchronized ROM source root' >&2; exit 1; }
full_build=0
if [[ ${1:-} == --full ]]; then
    full_build=1
    shift
    [[ $# == 0 ]] || { echo '--full selects the complete ROM target' >&2; exit 1; }
fi
if [[ -n ${SHENG_LUNCH:-} ]]; then
    lunch_choice=$SHENG_LUNCH
elif [[ -f vendor/custom/config/common_full_tablet_wifionly.mk ]]; then
    lunch_choice=custom_sheng-cp2a-userdebug
else
    lunch_choice=lineage_sheng-cp2a-userdebug
fi
[[ "$lunch_choice" =~ ^(lineage_sheng|custom_sheng)-[a-z0-9_]+-(user|userdebug|eng)$ ]] || {
    echo 'SHENG_LUNCH must select a sheng product, release and build variant' >&2; exit 1;
}
product=${lunch_choice%%-*}
jobs=${SHENG_BUILD_JOBS:-$(nproc)}
stage_face_engine=${SHENG_STAGE_FACE_ENGINE:-1}
analysis_memory_gib=${SHENG_ANALYSIS_MEMORY_GIB:-16}
analysis_cpus=${SHENG_ANALYSIS_CPUS:-6}
[[ "$jobs" =~ ^[1-9][0-9]*$ && "$jobs" -le 24 ]] || { echo 'SHENG_BUILD_JOBS must be between 1 and 24' >&2; exit 1; }
[[ "$stage_face_engine" == 0 || "$stage_face_engine" == 1 ]] || {
    echo 'SHENG_STAGE_FACE_ENGINE must be 0 or 1' >&2; exit 1;
}
[[ "$analysis_memory_gib" =~ ^[1-9][0-9]*$ && "$analysis_memory_gib" -ge 4 && "$analysis_memory_gib" -le 16 ]] || {
    echo 'SHENG_ANALYSIS_MEMORY_GIB must be between 4 and 16' >&2; exit 1;
}
[[ "$analysis_cpus" =~ ^[1-6]$ ]] || {
    echo 'SHENG_ANALYSIS_CPUS must be between 1 and 6' >&2; exit 1;
}
for target in "$@"; do
    [[ "$target" =~ ^[A-Za-z0-9_][-A-Za-z0-9_./@+]*$ && "/$target/" != *'/../'* ]] || {
        echo 'Invalid build target' >&2; exit 1;
    }
done
# Guard storage before touching the output lock or staging Settings/Shell.
requested_out=${OUT_DIR:-$rom/out}
requested_logs=${SHENG_BUILD_LOG_DIR:-$requested_out/sheng-build}
storage_args=()
[[ "$full_build" == 0 ]] || storage_args+=(--full)
python3 -B "$here/check_sheng_build_storage.py" "${storage_args[@]}" -- \
    "$rom" "$requested_out" "$requested_logs" "${TMPDIR:-/tmp}" "$here"
build_out=$(realpath -m --relative-to="$rom" -- "${OUT_DIR:-$rom/out}")
export OUT_DIR="$build_out"
mkdir -p "$build_out"
# Share the dedicated device builder's lock before staging or auditing inputs.
exec 9>"$build_out/.sheng-device-modules.lock"
flock -n 9 || { echo 'Another device module build owns the output lock' >&2; exit 1; }
if [[ -f "$build_out/.sheng-product" && "$(cat "$build_out/.sheng-product")" != "$product" ]]; then
    echo 'This output belongs to another ROM; use its separate source and output directory' >&2
    exit 1
fi
log_root=${SHENG_BUILD_LOG_DIR:-$rom/$build_out/sheng-build}
mkdir -p "$log_root"
run=$(mktemp -d "$log_root/run-XXXXXX")
builder="$rom/$build_out/host/linux-x86/bin/soong_build"
real_builder="$builder.sheng-real"
require_idle_analyzer() {
    if [[ -e "$real_builder" ]] || pgrep -f '(^|/)soong_build(\.sheng-real)?( |$)' > /dev/null; then
        echo 'Another build owns the Soong analyzer; refusing to overlap' >&2
        exit 1
    fi
}
require_idle_analyzer
# Native Settings controls stay source-owned in the device tree. Stage before
# Soong scans Settings' Java/resource globs; this creates no standalone APK.
if [[ "$product" == custom_sheng ]]; then
    python3 "$here/prepare_sheng_desktop_settings.py" --rom "$rom" \
        --output "$run/desktop-settings-staging.json"
    python3 "$here/prepare_sheng_desktop_shell.py" --rom "$rom" \
        --output "$run/desktop-shell-staging.json"
fi
# Enforce the user's C-only swap policy before build preparation.
python3 device/xiaomi/sheng/tools/prepare_sheng_stylus_swap.py --work "$run" \
    --create-gib "${SHENG_BUILD_SWAP_GIB:-32}"
python3 device/xiaomi/sheng/tools/audit_sheng_product_apps.py --output "$run/product-apps.json"
if [[ -n "${SHENG_SOURCE_WORKSPACE:-}" ]]; then
    # Public-repository checks cannot detect drift in this separate device tree.
    # Check before staging dependencies or changing any generated build output.
    mirror_args=()
    read -r -a mirror_scopes <<< "${SHENG_SOURCE_SCOPE:-}"
    for mirror_scope in "${mirror_scopes[@]}"; do
        mirror_args+=(--path "$mirror_scope")
    done
    python3 "$SHENG_SOURCE_WORKSPACE/device/xiaomi/sheng/tools/verify_device_source_mirror.py" \
        --workspace "$SHENG_SOURCE_WORKSPACE" --rom "$rom" \
        --output "$run/device-source-mirror-prebuild.json" "${mirror_args[@]}"
fi
# This only stages build dependencies; it does not control a runtime HAL.
if [[ "$stage_face_engine" == 1 && -d device/xiaomi/sheng/interfaces/biometrics/systemface ]]; then
    face_args=(--verify-only)
    if [[ -n ${SHENG_FACE_ENGINE_DIR:-} ]]; then
        face_args=(--engine-dir "$SHENG_FACE_ENGINE_DIR")
    fi
    python3 device/xiaomi/sheng/tools/prepare_sheng_face_engine.py "${face_args[@]}" \
        --output "$run/face-engine-staging.json"
fi
systemui_source=frameworks/base/libs/WindowManager/Shell/src/com/android/wm/shell/transition/RemoteTransitionHandler.java
systemui_sha256=2fa655846ce8a47b9b237ef1ba8afbaefa92b0758cdd892cfbd4dc15aea39055
cleaner_source=bionic/libc/Android.bp
cleaner_sha256=7cc7cdefb4fce841edb810cb3d5d7e81a465b8df9dc4383077ae5a863a0ce487
kernel_headers_source=vendor/lineage/build/soong/Android.bp
kernel_headers_sha256=4321b081fe6c9d1d6883e56646170c64698c876acda2c6708a7fbbcc271bbb42
header_cleanup_source=vendor/lineage/tools/clean_headers.sh
header_cleanup_sha256=36fee40e7f90838a9fa5e7cc9178389f080135691f8277b6766bd4df08298df8
header_generator_source=vendor/lineage/build/soong/generator/generator.go
header_generator_sha256=28f842bff06d16e7fe20ac918d2438f2966e000f32c1aef46138abe180b74775
desktop_audit_args=()
if [[ "$product" == custom_sheng ]]; then
    # The device-owned home-transition patch changes this audited source too.
    # Keep Lineage's baseline separate from the PixelOS desktop integration.
    systemui_sha256=67c45101e685abc2b8a3e7c69c3dced76e1475aafdbb4cab660525c51cd2876d
    desktop_audit_args+=(--allow-modified 'frameworks/base/libs/WindowManager/Shell/src/com/android/wm/shell/transition/ShengDesktopHomeTransition.java=ad1bacc811a6d8e38c6388ddb67ecbb8b69df4868e34c2386811cc2ce7857403')
    desktop_audit_args+=(--allow-modified 'frameworks/base/libs/WindowManager/Shell/src/com/android/wm/shell/desktopmode/DesktopTasksController.kt=be1ed92633277d7dc778902e9a5dc0388d93694930be471b7f1fa1d88b7b0522')
    desktop_audit_args+=(--allow-modified 'frameworks/base/libs/WindowManager/Shell/src/com/android/wm/shell/windowdecor/common/CaptionVisibilityHelper.kt=953f7b2b23dcd83b0ecd1f0091e6444931802dd2afc0370f2036fd76dedd33e8')
    desktop_audit_args+=(--allow-modified 'frameworks/base/libs/WindowManager/Shell/src/com/android/wm/shell/desktopmode/desktopfirst/DesktopDisplayModeController.kt=a98eef295487f817c88c49cee3ce85bdba8528a497038b6590a00c91f0185d66')
    desktop_audit_args+=(--allow-modified 'packages/apps/Settings/AndroidManifest.xml=d2cf370805e34d019324ffb7fbe2ed4f6dda29267225809085ca4a142374da5c')
    desktop_audit_args+=(--allow-modified 'packages/apps/Settings/src/com/android/settings/core/gateway/SettingsGateway.java=112dad2eb30ac04f248d31ba262f0e6c1ab47833eb9ae8061addbcf5c5d154d4')
    desktop_audit_args+=(--allow-modified 'packages/apps/Settings/src/com/android/settings/homepage/TopLevelSettings.java=63d430bd3afc8ee5e707f1b22894a6e43621e32511d7b72661e598c6f98b0682')
    desktop_audit_args+=(--allow-modified 'packages/apps/Settings/src/com/android/settings/qstile/QSTileLongPressGatewayActivity.kt=e2eb7dc61325047a8ae31e04f892037a5d7e2835920701741b840310ca99316f')
    desktop_audit_args+=(--allow-modified 'packages/apps/Settings/src/com/android/settings/sheng/DesktopModeSettings.java=78201034ab67ba3dd23a69f3a385836ca8691aa0e8601d0b28be171320f8cc86')
    desktop_audit_args+=(--allow-modified 'packages/apps/Settings/res/drawable/tile_icon_desktop_mode.xml=878508fbf4161dc8dcca938b473846033daea7789ddaa26de4efe4812ef30547')
    desktop_audit_args+=(--allow-modified 'packages/apps/Settings/res/values/sheng_desktop_strings.xml=c553f3b49e8bc5438913f9443bfe77c3ad54c4c2be8f86a64f644fb32b9c4537')
    desktop_audit_args+=(--allow-modified 'packages/apps/Settings/res/values-zh-rCN/sheng_desktop_strings.xml=7c871b237f44486218d2e313e6a9205a6383ddb5391fe6ad8a31d7f8bbe82a26')
    desktop_audit_args+=(--allow-modified 'packages/apps/Settings/res/xml/sheng_desktop_settings.xml=72d78972bbb1f9460aed31bb0c233981e7c3583be427a10b730e442db7a8be16')
fi
python3 device/xiaomi/sheng/tools/audit_upstream_sources.py --fetch --rom "$rom" \
    "${desktop_audit_args[@]}" \
    --allow-modified "$systemui_source=$systemui_sha256" \
    --allow-modified "$cleaner_source=$cleaner_sha256" \
    --allow-modified "$kernel_headers_source=$kernel_headers_sha256" \
    --allow-modified "$header_cleanup_source=$header_cleanup_sha256" \
    --allow-modified "$header_generator_source=$header_generator_sha256" \
    --output "$run/prebuild-upstream-source-audit.json"
set +u
source build/envsetup.sh
lunch "$lunch_choice"
set -u
[[ "$(get_build_var PRODUCT_ENFORCE_PRODUCT_PARTITION_INTERFACE)" == false ]] || {
    echo 'Device product applications require the configured platform API access' >&2; exit 1;
}
printf '%s\n' "$product" > "$build_out/.sheng-product"
export USE_CCACHE=1 CCACHE_EXEC=/usr/bin/ccache
export CCACHE_DIR=${CCACHE_DIR:-$rom/../ccache} CCACHE_COMPRESS=true
export SOONG_ALLOW_MISSING_DEPENDENCIES=false
export SOONG_NINJA=ninja
# The 20 GiB host cannot run many 4 GiB Java tools at once without swap thrashing.
export NINJA_HIGHMEM_NUM_JOBS=2
"$CCACHE_EXEC" --max-size=10G >/dev/null
# Finish the generated compiler's bootstrap before wrapping it. The temporary
# wrapper must not be replaced by a pending Ninja copy/link action.
require_idle_analyzer
if [[ -f "$build_out/soong/bootstrap.ninja" ]]; then
    prebuilts/build-tools/linux-x86/bin/ninja -f "$build_out/soong/bootstrap.ninja" \
        "$build_out/host/linux-x86/bin/soong_build"
fi
# Soong's hermetic launcher strips environment variables. On this 20 GiB WSL
# host, use a temporary wrapper around the generated compiler output to pass
# Go's supported heap target; this is not a hard resident-memory bound.
# Restore the output when this build finishes;
# public source and normal product builds are unaffected.
require_idle_analyzer
if [[ -f "$builder" ]]; then
    mv -- "$builder" "$real_builder"
    owns_wrapper=true
    wrapper_sha=
    restore_builder() {
        result=$?
        if [[ ${owns_wrapper:-false} == true && -f "$real_builder" ]]; then
            if [[ -z "$wrapper_sha" ]] || [[ -f "$builder" && $(sha256sum "$builder" | cut -d ' ' -f 1) == "$wrapper_sha" ]]; then
                mv -f -- "$real_builder" "$builder" || result=1
            else
                # Preserve an unexpected output and its recoverable compiler.
                echo 'Soong output changed outside this build; retaining its compiler backup' >&2
                result=1
            fi
        fi
        return "$result"
    }
    trap restore_builder EXIT
    # Blueprint resets GOMAXPROCS to NumCPU; affinity must constrain NumCPU
    # before Go starts to bound concurrent analysis allocations on this host.
    build_cpus=$(python3 -c 'import os, sys; print(",".join(map(str, sorted(os.sched_getaffinity(0))[:int(sys.argv[1])])))' "$analysis_cpus")
    printf '#!/bin/sh\nexport GOMEMLIMIT=%sGiB GOGC=50\nexec /usr/bin/taskset -c "%s" "%s" "$@"\n' "$analysis_memory_gib" "$build_cpus" "$real_builder" > "$builder"
    chmod 755 "$builder"
    # Do not invalidate an unchanged build graph just for the memory wrapper.
    touch -r "$real_builder" "$builder"
    wrapper_sha=$(sha256sum "$builder" | cut -d ' ' -f 1)
fi
targets=(
    audio.primary.sheng libar-pal
    android.hardware.sensors-service.sheng-multihal
    vendor.qti.hardware.display.composer-service-sheng
    vendor.qti.hardware.display.allocator-service-sheng
    "$build_out"/target/product/sheng/vendor/lib64/libsdmdal.so
    "$build_out"/target/product/sheng/vendor/lib64/libsdedrm.so
    libshgdolby_foundation libdlbdsservice libhwdap libdlbpreg libdlbvol
    "$build_out"/target/product/sheng/vendor/build.prop "$build_out"/target/product/sheng/odm/etc/build.prop
    ShengDolby FrameworkResOverlaySheng NetworkStackResOverlaySheng
    vendor_file_contexts selinux_policy file_contexts.bin
)
# Desktop source preparation must be accompanied by its actual APK targets.
# Otherwise a hardware-only run leaves the previous Settings/SystemUI installed.
if [[ "$product" == custom_sheng && "$full_build" == 0 && $# == 0 ]]; then
    targets+=(Settings SystemUI ShengKeyboardPresence SettingsResOverlaySheng)
fi
if [[ "$full_build" == 1 ]]; then
    if [[ "$product" == custom_sheng ]]; then
        targets=(pixelos)
    else
        targets=(bacon)
    fi
elif [[ $# -gt 0 ]]; then
    targets=("$@")
fi
m -j"$jobs" "${targets[@]}"
if [[ "$product" == custom_sheng ]]; then
    # A staged .java file is not proof that the shipped Settings contains the
    # desktop page. Reject the exact installed APK when this run built Settings.
    desktop_apk_check=$full_build
    for target in "${targets[@]}"; do
        [[ "$target" != Settings ]] || desktop_apk_check=1
    done
    if [[ "$desktop_apk_check" == 1 ]]; then
        desktop_menu_args=()
        if [[ "$full_build" == 1 ]]; then
            desktop_menu_args=(--overlay "$rom/$build_out/target/product/sheng/odm/overlay/SettingsResOverlaySheng.apk"
                --aapt2 "$rom/$build_out/host/linux-x86/bin/aapt2")
        fi
        python3 "$here/verify_sheng_desktop_apk.py" \
            "$rom/$build_out/target/product/sheng/system_ext/priv-app/Settings/Settings.apk" \
            "${desktop_menu_args[@]}" \
            | tee "$run/desktop-settings-apk.json"
    fi
fi
if [[ "$full_build" == 1 && "$product" == custom_sheng ]]; then
    m -j"$jobs" idmap2-host aapt2
    python3 "$here/verify_sheng_network_artifacts.py" \
        --product "$rom/$build_out/target/product/sheng" \
        --host-bin "$rom/$build_out/host/linux-x86/bin" \
        | tee "$run/network-artifacts.json"
    python3 "$here/verify_sheng_network_artifacts.py" \
        --target-files-dir "$rom/$build_out/target/product/sheng/obj/PACKAGING/target_files_intermediates/$product-target_files" \
        --host-bin "$rom/$build_out/host/linux-x86/bin" \
        | tee "$run/network-target-files.json"
fi
