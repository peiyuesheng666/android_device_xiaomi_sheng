#!/system/bin/sh
# Bounded read-only capture; never changes display configuration or clears logs.
set -eu
test "$(id -u)" = 0
test "$(getprop ro.boot.serialno)" = ca10ede3
out=$(mktemp -d /data/local/tmp/sheng-dp-transition-XXXXXX)
chmod 0700 "$out"
echo "$out"
{
    date
    cat /proc/sys/kernel/random/boot_id
    getprop ro.boot.slot_suffix
    getprop sys.boot_completed
} >"$out/identity.txt"
# A hard per-file limit also bounds unexpected verbose vendor logging.
ulimit -f 4096
timeout 120 logcat -b all -v threadtime -T 1 -f "$out/logcat.txt" -r 1024 -n 2 &
logpid=$!
# -w replays the entire ring first and can exhaust the cap before a transition.
# Preserve a bounded baseline separately, then follow new messages with -W.
# Toybox's /dev/kmsg reader does not bound output with -s. Bound the pipe
# explicitly so historical logs cannot exhaust RLIMIT_FSIZE before -W starts.
timeout 3 dmesg 2>&1 | tail -c 262144 >"$out/kernel-before.txt" || true
timeout 120 dmesg -W >"$out/kernel.txt" 2>&1 &
kernelpid=$!
trap 'kill "$logpid" "$kernelpid" 2>/dev/null || true' EXIT HUP INT TERM
i=0
while test "$i" -lt 60; do
    {
        echo "=== sample=$i ==="
        date
        cat /proc/uptime
        timeout 2 cat /sys/kernel/debug/drm_dp/dp_debug || true
        if test $((i % 3)) = 0; then
            timeout 2 /data/local/tmp/sheng-drm-color-probe || true
        fi
    } >>"$out/mode-color-timeline.txt" 2>&1
    i=$((i + 1))
    sleep 2
done
wait "$logpid" || true
wait "$kernelpid" || true
echo completed >"$out/completed"
echo "saved=$out"
