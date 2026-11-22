#!/system/bin/sh
# Single-APK, volatile SystemUI trial. No PackageManager/partition replacement.
set -eu
T=/system_ext/priv-app/SystemUI/SystemUI.apk
C=/data/local/tmp/sheng-SystemUI-manual-trial.apk
BASE=211c5be70e4fca7a4852220b889c9b036363dd6e40cdaaeae466a003f112b376
NEXT=a492985b608a224c8dd98641ce8867033a64bc055fd2935ab5ccb17783062729
test "$(id -u)" = 0
test "$(getprop ro.serialno)" = ca10ede3
test "$(getprop ro.boot.slot_suffix)" = _b
test "$(getenforce)" = Enforcing
digest() { nsenter -t "$1" -m -- sha256sum "$T" | cut -d ' ' -f 1; }
if [ "${1:-}" = --watchdog ]; then
    D=$2
    sleep 35
    test ! -e "$D/keep" || exit 0
    while read -r pid; do
        if [ "$(digest "$pid")" = "$NEXT" ]; then
            nsenter -t "$pid" -m -- umount -l "$T"
        fi
    done <"$D/mount-pids"
    p=$(pidof com.android.systemui)
    test -z "$p" || kill "$p"
    echo ROLLED_BACK >"$D/watchdog-result"
    exit 0
fi
test "$(getprop sys.boot_completed)" = 1
test "$(settings get global sheng_desktop_enabled)" = 0
test "$(digest 1)" = "$BASE"
test "$(sha256sum "$C" | cut -d ' ' -f 1)" = "$NEXT"
z=$(pidof zygote64)
old=$(pidof com.android.systemui)
case "$z:$old" in *' '*|:|:*) exit 1;; esac
test -n "$z" && test -n "$old"
test "$(digest "$z")" = "$BASE"
D=$(mktemp -d /data/local/tmp/sheng-desktop-trial-XXXXXX)
chmod 0755 "$D"
touch "$D/mount-pids"
echo "$D"
chmod 0644 "$C"
chcon u:object_r:system_file:s0 "$C"
nohup "$0" --watchdog "$D" </dev/null >"$D/watchdog-log" 2>&1 &
echo "$!" >"$D/watchdog-pid"
for pid in 1 "$z"; do
    current=$(digest "$pid")
    if [ "$current" = "$BASE" ]; then
        echo "$pid" >>"$D/mount-pids"
        nsenter -t "$pid" -m -- mount --bind "$C" "$T"
        nsenter -t "$pid" -m -- /data/adb/ksu/bin/busybox mount \
            -o remount,bind,ro,nodev,exec "$C" "$T"
    else
        test "$current" = "$NEXT"
    fi
done
kill "$old"
sleep 10
p=$(pidof com.android.systemui)
test -n "$p" && test "$p" != "$old"
test "$(digest "$p")" = "$NEXT"
timeout 12 dumpsys activity service com.android.systemui/.SystemUIService WMShell >"$D/shell.txt"
grep -q 'targetWindowingModeForDefaultDisplay=1' "$D/shell.txt"
grep -q 'Display#0 isDesktopFirst=false' "$D/shell.txt"
test "$(settings get global sheng_desktop_enabled)" = 0
{
    echo "old_pid=$old new_pid=$p"
    cat "/proc/$p/attr/current"
    echo
    echo "apk_sha256=$(digest "$p")"
    getenforce
    grep -E 'targetWindowingModeForDefaultDisplay=|Display#[0-9]+ isDesktopFirst=' "$D/shell.txt"
} >"$D/runtime.txt"
touch "$D/keep"
chmod 0644 "$D/runtime.txt" "$D/shell.txt"
cat "$D/runtime.txt"
echo STARTED_FOR_FUNCTIONAL_TEST
