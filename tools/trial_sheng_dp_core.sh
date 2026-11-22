#!/system/bin/sh
# Temporary single-library trial. Original vendor filesystem remains untouched.
set -eu
T=/vendor/lib64/libsdmcore.so
C=/data/local/tmp/sheng-dp-core-vsync-candidate.so
S=vendor.qti.hardware.display.composer
expected=f2eb6f50a922b3beeadc0e6a416234d5203680eef7e7ac0f010156a49f292ad0
test "$(id -u)" = 0
test "$(getprop ro.boot.serialno)" = ca10ede3
test "$(getprop ro.boot.slot_suffix)" = _b
if [ "${1:-}" = --watchdog ]; then
    D=$2
    sleep 35
    test ! -f "$D/keep" || exit 0
    if nsenter -t 1 -m -- sha256sum "$T" | grep -q "^$expected "; then
        nsenter -t 1 -m -- umount -l "$T"
        setprop ctl.restart "$S"
        echo ROLLED_BACK >"$D/watchdog-result"
    fi
    exit 0
fi
test "$(getprop sys.boot_completed)" = 1
nsenter -t 1 -m -- sha256sum "$T" | grep -q '^17bea323b5325fedba8c1426ce468beff361573150f7ed5b23f2cfde9a831d40 '
sha256sum "$C" | grep -q "^$expected "
D=$(mktemp -d /data/local/tmp/sheng-dp-core-trial-XXXXXX)
echo "$D"
chmod 0755 "$D"
chown 0:2000 "$C"
chmod 0644 "$C"
chcon u:object_r:vendor_file:s0 "$C"
nohup /system/bin/sh "$0" --watchdog "$D" </dev/null >"$D/watchdog-log" 2>&1 &
echo "$!" >"$D/watchdog-pid"
nsenter -t 1 -m -- mount --bind "$C" "$T"
nsenter -t 1 -m -- /data/adb/ksu/bin/busybox mount -o remount,bind,ro,nodev,exec "$C" "$T"
setprop ctl.restart "$S"
sleep 10
logcat -b all -d -t 3000 >"$D/logcat.txt"
timeout 10 dumpsys SurfaceFlinger >"$D/surfaceflinger.txt" || exit 1
pid=$(pidof vendor.qti.hardware.display.composer-service-sheng)
test -n "$pid"
grep -q '/vendor/lib64/libsdmcore.so' "/proc/$pid/maps"
grep -q 'Display 4630947038039379843' "$D/surfaceflinger.txt"
ps -AZ | grep "$pid" | grep -q 'u:r:hal_graphics_composer_default:s0'
nsenter -t 1 -m -- sha256sum "$T" | grep -q "^$expected "
{
    echo "pid=$pid"
    getenforce
    nsenter -t 1 -m -- sha256sum "$T"
    cat "/proc/$pid/maps"
} >"$D/runtime.txt"
touch "$D/keep"
chmod 0644 "$D/logcat.txt" "$D/surfaceflinger.txt" "$D/runtime.txt"
echo STARTED_FOR_VISUAL_TEST
