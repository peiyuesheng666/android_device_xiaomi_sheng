#!/system/bin/sh
# Bounded, isolated DRM event tracing; does not change display settings.
set -eu
test "$(id -u)" = 0
test "$(getprop ro.boot.serialno)" = ca10ede3
base=/sys/kernel/debug/tracing/instances
instance="$base/sheng_dp_vblank_$$"
mkdir "$instance"
cleanup() {
    echo 0 >"$instance/tracing_on" || true
    echo 0 >"$instance/events/drm/enable" || true
    rmdir "$instance" || true
}
trap cleanup EXIT HUP INT TERM
echo 0 >"$instance/tracing_on"
echo 256 >"$instance/buffer_size_kb"
for event in drm_vblank_event drm_vblank_event_queued drm_vblank_event_delivered; do
    echo 1 >"$instance/events/drm/$event/enable"
done
echo 1 >"$instance/tracing_on"
sleep 12
echo 0 >"$instance/tracing_on"
cat "$instance/trace"
