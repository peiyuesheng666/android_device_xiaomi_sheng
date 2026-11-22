#!/system/bin/sh
# One diagnostic role transition after firmware readiness, not a boot workaround.
# Tmpfs logs only; no partition writes, reboot, forced polarity or speed cap.
set -eu
out=/tmp/sheng-role-readiness-20261119
mode=/sys/bus/platform/devices/a600000.ssusb/mode
[ "$(id -u)" = 0 ]
[ "$(getprop ro.serialno)" = ca10ede3 ]
[ "$(getprop ro.product.device)" = sheng ]
[ "$(getprop ro.boot.slot_suffix)" = _b ]
[ "$(getprop init.svc.recovery)" = running ]
[ "$(getprop sys.usb.config)" = adb ]
grep -q 'sheng_bootlog.enable=0' /proc/cmdline
[ "$(cat "$mode")" = peripheral ]
[ ! -e "$out" ]
cc=$(cat /sys/class/qcom-battery/cc_orientation)
case "$cc" in 1|2) ;; *) exit 1 ;; esac
echo $$ > /sys/fs/cgroup/cgroup.procs
[ "$(cat /proc/$$/cgroup)" = '0::/' ]
mkdir "$out"
echo running > "$out/status"
echo "$cc" > "$out/firmware-cc-before.txt"
cat /proc/sys/kernel/random/boot_id > "$out/boot-id.txt"
dmesg > "$out/dmesg-before.txt"
dd if=/dev/block/by-name/rawdump of="$out/rawdump-before.bin" bs=1048576 skip=288 count=2 2>"$out/rawdump-before-dd.txt"
restore() {
    timeout 5 sh -c 'echo peripheral > /sys/bus/platform/devices/a600000.ssusb/mode' >> "$out/restore.txt" 2>&1 || true
}
trap restore EXIT
echo none > "$mode"
# Diagnostic settling interval, NOT a provider-readiness implementation.
sleep 2
cat "$mode" > "$out/idle-mode.txt"
echo peripheral > "$mode"
i=0
while [ "$i" -lt 15 ]; do
    sleep 2
    {
        echo '=== SNAPSHOT ==='
        cat /proc/uptime "$mode"
        cat /sys/class/udc/a600000.dwc3/current_speed /sys/class/udc/a600000.dwc3/state
    } >> "$out/samples.txt"
    i=$((i+1))
done
dmesg > "$out/dmesg-after.txt"
dd if=/dev/block/by-name/rawdump of="$out/rawdump-after.bin" bs=1048576 skip=288 count=2 2>"$out/rawdump-after-dd.txt"
restore
trap - EXIT
echo completed > "$out/status"
