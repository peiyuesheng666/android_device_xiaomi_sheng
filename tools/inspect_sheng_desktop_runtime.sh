#!/system/bin/sh
# Read-only inspection. Run the script itself through su, not a host-quoted
# command chain whose later commands can accidentally execute as shell UID.
set -eu
test "$(id -u)" = 0
test "$(getprop ro.serialno)" = ca10ede3
id
cat /proc/self/attr/current
echo
for name in zygote64 system_server com.android.systemui; do
    p=$(pidof "$name")
    test -n "$p"
    case "$p" in *' '*) echo "Ambiguous PID for $name"; exit 1;; esac
    echo "$name pid=$p namespace=$(readlink /proc/$p/ns/mnt)"
    nsenter -t "$p" -m -- sha256sum /system_ext/priv-app/SystemUI/SystemUI.apk
done
