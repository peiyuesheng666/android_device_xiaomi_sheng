#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Opt-in Recovery-only observer. Start from init, not an ADB session cgroup.
# Files go only to existing /tmp tmpfs. No partition, role, PHY or mount writes.
# Returning the Recovery UI to ADB is separately gated, and happens AFTER capture.
set -eu
umask 077
[ "$(id -u)" = 0 ] || exit 1
[ "$(getprop ro.serialno)" = ca10ede3 ] || exit 1
[ "$(getprop ro.product.device)" = sheng ] || exit 1
[ "$(getprop ro.boot.slot_suffix)" = _b ] || exit 1
[ "$(getprop ro.boot.sheng_fastboot_trace)" = 1 ] || exit 1
[ "$(getprop ro.boot.force_normal_boot)" != 1 ] || exit 1
[ -x /system/bin/recovery ] || exit 1
grep -Eq '(^|[[:space:]])sheng_bootlog\.enable=0([[:space:]]|$)' /proc/cmdline || exit 1
grep -q ' /tmp tmpfs ' /proc/mounts || exit 1

boot=$(cat /proc/sys/kernel/random/boot_id)
case "$boot" in ''|*[!a-f0-9-]*) exit 1 ;; esac
out=/tmp/sheng-fastbootd-cold-$boot
# mkdir atomically refuses duplicate launches. Never overwrite failed evidence.
mkdir "$out" || exit 1
exec >"$out/status.txt" 2>&1
echo running
printf '%s\n' "$boot" > "$out/boot-id.txt"
cat /proc/self/cgroup > "$out/worker-cgroup.txt"
cat /proc/cmdline > "$out/cmdline.txt"
getprop > "$out/properties-before.txt"
dmesg > "$out/dmesg-before.txt"

snapshot() {
    cat /proc/uptime
    for prop in sys.usb.config sys.usb.state sys.usb.ffs.ready init.svc.fastbootd init.svc.recovery; do
        printf '%s=' "$prop"; getprop "$prop"
    done
    for f in /sys/class/udc/*/current_speed /sys/class/udc/*/state \
             /sys/class/typec/port*/data_role /sys/class/typec/port*/orientation \
             /config/usb_gadget/g1/UDC; do
        [ -r "$f" ] || continue
        printf '%s=' "$f"; timeout 1 cat "$f" || true
    done
    for pid in $(pidof fastbootd || true); do
        # A small per-thread capture, not repeated full process maps.
        for thread in /proc/"$pid"/task/*; do
            echo "$thread"
            timeout 1 cat "$thread/comm" "$thread/wchan" "$thread/stack" || true
        done
    done
}

snapshot > "$out/before.txt" 2>&1
read -r now rest < /proc/uptime
end=$((${now%.*}+120))
i=0
while [ "$i" -lt 60 ]; do
    # Bound individual sysfs/task reads; init bounds the service to 180 seconds.
    # Missing or stuck debug paths must not prevent the final log capture.
    echo "=== SAMPLE $i ===" >> "$out/samples.txt"
    snapshot >> "$out/samples.txt" 2>&1
    read -r now rest < /proc/uptime
    [ "${now%.*}" -lt "$end" ] || break
    sleep 2
    i=$((i+1))
done
dmesg > "$out/dmesg-after.txt"
getprop > "$out/properties-after.txt"
cp /tmp/recovery.log "$out/recovery.log" 2>/dev/null || true
echo captured > "$out/result.txt"

# Do not change mode during observation. Optional rescue uses the same official
# Recovery socket as the warm-transition experiment, never a reboot or flash.
if [ "$(getprop ro.boot.sheng_fastboot_trace_return_adb)" = 1 ]; then
    if [ "$(getprop sys.usb.config)" = fastboot ]; then
        if printf r | timeout 3 nc -U -q 1 /dev/socket/recovery > "$out/return-adb.txt" 2>&1; then
            sleep 4
            getprop sys.usb.config >> "$out/return-adb.txt"
        else
            echo 'Recovery socket return failed; evidence remains in tmpfs' >> "$out/return-adb.txt"
        fi
    fi
fi
echo completed
