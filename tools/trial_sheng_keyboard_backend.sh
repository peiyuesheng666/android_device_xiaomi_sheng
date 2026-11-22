#!/system/bin/sh
# Volatile APK-only trial. PackageManager metadata is deliberately unchanged.
set -eu
T=/product/priv-app/ShengKeyboardPresence/ShengKeyboardPresence.apk
C=/data/local/tmp/sheng-keyboard-backend-candidate.apk
BASE=1715d91bb33e67eb4019fe982a55b0476fb0e0af65094c22d49462738db04e23
NEXT=e95b9048cec05ec20cbad09c8042cb745aaf1011178fa94a6b483cc60ed9aec5
test "$(id -u)" = 0
test "$(getprop ro.serialno)" = ca10ede3
test "$(getprop ro.boot.slot_suffix)" = _b
digest() { nsenter -t "$1" -m -- sha256sum "$T" | cut -d ' ' -f 1; }
if [ "${1:-}" = --watchdog ]; then
    D=$2
    sleep 40
    test ! -e "$D/keep" || exit 0
    while read -r p; do
        if [ "$(digest "$p")" = "$NEXT" ]; then
            nsenter -t "$p" -m -- umount -l "$T"
        fi
    done <"$D/mount-pids"
    p=$(pidof org.lineageos.sheng.keyboard)
    test -z "$p" || kill "$p"
    echo ROLLED_BACK >"$D/watchdog-result"
    exit 0
fi
test "$(getprop sys.boot_completed)" = 1
test "$(getenforce)" = Enforcing
z=$(pidof zygote64)
old=$(pidof org.lineageos.sheng.keyboard)
case "$z:$old" in *' '*|:*|*:) exit 1;; esac
test "$(digest 1)" = "$BASE"
test "$(digest "$z")" = "$BASE"
test "$(sha256sum "$C" | cut -d ' ' -f 1)" = "$NEXT"
D=$(mktemp -d /data/local/tmp/sheng-keyboard-backend-XXXXXX)
chmod 0755 "$D"
touch "$D/mount-pids"
chmod 0644 "$C"
chcon u:object_r:system_file:s0 "$C"
nohup "$0" --watchdog "$D" </dev/null >"$D/watchdog-log" 2>&1 &
echo "$D"
for p in 1 "$z"; do
    if [ "$(digest "$p")" = "$BASE" ]; then
        echo "$p" >>"$D/mount-pids"
        nsenter -t "$p" -m -- mount --bind "$C" "$T"
        nsenter -t "$p" -m -- /data/adb/ksu/bin/busybox mount -o remount,bind,ro,nodev,exec "$C" "$T"
    else
        test "$(digest "$p")" = "$NEXT"
    fi
done
kill "$old"
sleep 10
p=$(pidof org.lineageos.sheng.keyboard)
test -n "$p" && test "$p" != "$old"
test "$(digest "$p")" = "$NEXT"
cat "/proc/$p/attr/current" | grep -q 'u:r:sheng_keyboard_app:'
# A changed path hash alone is insufficient: require the APK mapped by ART.
grep -F "$T" "/proc/$p/maps" >"$D/apk-maps.txt"
{
    echo "old_pid=$old new_pid=$p"
    echo "apk_sha256=$(digest "$p")"
    cat "/proc/$p/attr/current"
    echo
    getenforce
} >"$D/runtime.txt"
touch "$D/keep"
chmod 0644 "$D/runtime.txt" "$D/apk-maps.txt"
cat "$D/runtime.txt"
echo LOADED_FOR_HARDWARE_TEST_NOT_ACCEPTED
