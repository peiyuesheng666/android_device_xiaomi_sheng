#!/system/bin/sh
# Read-only display-state capture. Does not modeset, retrain, or write debugfs.
set -eu
test "$(id -u)" = 0
test "$(getprop ro.boot.serialno)" = ca10ede3
label=${1:-snapshot}
case "$label" in bad|good|snapshot) ;; *) exit 2 ;; esac
out=$(mktemp -d "/data/local/tmp/sheng-dp-color-${label}-XXXXXX")
chmod 0700 "$out"
{
    echo "label=$label"
    echo "boot_id=$(cat /proc/sys/kernel/random/boot_id)"
    echo "uptime=$(cat /proc/uptime)"
    echo "slot=$(getprop ro.boot.slot_suffix)"
    echo "boot_completed=$(getprop sys.boot_completed)"
    echo "serial=$(getprop ro.boot.serialno)"
    uname -a
    id
    cat /proc/self/attr/current
    getenforce
    nsenter -t 1 -m -- sha256sum /vendor/bin/hw/vendor.qti.hardware.display.composer-service-sheng
    nsenter -t 1 -m -- sha256sum /vendor/lib64/libsdmcore.so
    pidof vendor.qti.hardware.display.composer-service-sheng || true
} >"$out/identity.txt"
timeout 15 dumpsys display >"$out/display.txt" 2>&1 || true
timeout 15 dumpsys SurfaceFlinger >"$out/surfaceflinger.txt" 2>&1 || true
{
    for f in /sys/class/drm/card*-DP-*/status /sys/class/drm/card*-DP-*/modes \
        /sys/kernel/debug/dri/*/state /sys/kernel/debug/dri/*/dp_debug \
        /sys/kernel/debug/dri/*/DP-*/dp_debug \
        /sys/kernel/debug/drm_dp/dp_debug; do
        test -f "$f" || continue
        echo "=== $f ==="
        timeout 5 cat "$f" || true
    done
} >"$out/drm-state.txt" 2>&1
{
    # Read only: do not select register banks or force a bit depth/modeset.
    for name in max_bpp widebus_mode hdr; do
        f="/sys/kernel/debug/drm_dp/$name"
        test -f "$f" || continue
        echo "=== $f ==="
        timeout 5 cat "$f" || true
    done
} >"$out/dp-color-policy.txt" 2>&1
dmesg | tail -600 >"$out/kernel.txt"
logcat -b all -d -t 2000 >"$out/logcat.txt"
cat /proc/1/mountinfo >"$out/init-mountinfo.txt"
# Read the runtime namespace rather than the caller's potentially stale mounts.
# Keep missing libraries explicit: vendor layouts differ between builds.
nsenter -t 1 -m -- /system/bin/sh -c '
    for f in /vendor/lib64/libpal.so /vendor/lib64/libar-pal.so \
        /vendor/lib64/libagm.so /vendor/lib64/hw/audio.primary.*.so; do
        if test -f "$f"; then
            sha256sum "$f"
        else
            echo "absent: $f"
        fi
    done
' >"$out/audio-library-hashes.txt" 2>&1
# Existing DP IPC history includes configuration values hidden from dmesg.
# Never use log_cont here: a snapshot must terminate and remain bounded.
if test -r /sys/kernel/debug/ipc_logging/drm_dp/log; then
    timeout 3 cat /sys/kernel/debug/ipc_logging/drm_dp/log 2>&1 |
        head -c 262144 >"$out/dp-ipc.txt" || true
fi
echo "$out"
