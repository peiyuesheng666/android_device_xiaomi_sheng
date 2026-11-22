#!/system/bin/sh
# One bounded Recovery/fastbootd experiment. Only tmpfs logs, worker cgroup and USB state change.
# No flashing, reboot, slot/snapshot transitions, mounts or partition writes.
set -u
out=${1:-/tmp/sheng-fastbootd-local-20261119}
case "$out" in /tmp/sheng-fastbootd-local-*) ;; *) exit 1 ;; esac
[ "$(id -u)" = 0 ] || exit 1
[ "$(getprop ro.serialno)" = ca10ede3 ] || exit 1
[ "$(getprop ro.product.device)" = sheng ] || exit 1
[ "$(getprop ro.boot.slot_suffix)" = _b ] || exit 1
[ "$(getprop init.svc.recovery)" = running ] || exit 1
grep -q 'sheng_bootlog.enable=0' /proc/cmdline || exit 1
[ "$(getprop sys.usb.config)" = adb ] || exit 1
[ ! -e "$out" ] || exit 1
# ADB's session cleanup kills descendants when Recovery stops adbd. nohup alone
# is insufficient: launch with setsid and move this root-only worker outside
# that session's cgroup before switching USB. Children inherit the root cgroup.
old_cgroup=$(cat /proc/$$/cgroup)
echo $$ > /sys/fs/cgroup/cgroup.procs || exit 1
[ "$(cat /proc/$$/cgroup)" = '0::/' ] || exit 1
mkdir "$out" || exit 1
printf '%s\n' "$old_cgroup" > "$out/original-worker-cgroup.txt"
cat /proc/$$/cgroup > "$out/worker-cgroup.txt"
echo $$ > "$out/pid"
echo running > "$out/status"
cat /proc/sys/kernel/random/boot_id > "$out/boot-id"
dmesg > "$out/dmesg-before.txt"
getprop > "$out/properties-before.txt"
dd if=/dev/block/by-name/rawdump of="$out/rawdump-before.bin" bs=1048576 skip=288 count=2 2>"$out/rawdump-before-dd.txt"
dmesg -w > "$out/dmesg-stream.txt" 2>&1 &
logger_pid=$!

switch_ui() {
    printf '%s' "$1" | timeout 3 nc -U -q 1 /dev/socket/recovery
}

cleanup() {
    switch_ui r >> "$out/switch-back.txt" 2>&1 || true
    sleep 4
    if [ "$(getprop sys.usb.config)" != adb ]; then
        echo 'UI did not restore adb; using Recovery init USB triggers' >> "$out/switch-back.txt"
        setprop sys.usb.config none
        sleep 2
        setprop sys.usb.config adb
    fi
    kill "$logger_pid" 2>/dev/null || true
    getprop sys.usb.config > "$out/restored-usb-config.txt"
}
trap cleanup EXIT

snapshot() {
    echo '=== SNAPSHOT ==='
    cat /proc/uptime
    for prop in sys.usb.config sys.usb.state init.svc.fastbootd init.svc.recovery; do
        printf '%s=' "$prop"; getprop "$prop"
    done
    for udc in /sys/class/udc/*; do
        echo "$udc"; cat "$udc/current_speed" "$udc/state" 2>/dev/null
    done
    for role in /sys/class/typec/port*/data_role /sys/class/typec/port*/orientation; do
        [ -f "$role" ] && { echo "$role"; cat "$role"; }
    done
    for pid in $(pidof fastbootd); do
        cat "/proc/$pid/status"
        for thread in /proc/"$pid"/task/*; do
            echo "$thread"
            cat "$thread/comm" "$thread/wchan" "$thread/stack" 2>/dev/null
        done
        ls -l "/proc/$pid/fd"
    done
}

snapshot > "$out/before.txt" 2>&1
switch_ui f > "$out/switch-fastboot.txt" 2>&1 || true
i=0
while [ "$i" -lt 30 ]; do
    sleep 2
    snapshot >> "$out/samples.txt" 2>&1
    i=$((i+1))
done
cp /tmp/recovery.log "$out/recovery.log" 2>/dev/null || true
dmesg > "$out/dmesg-after.txt"
dd if=/dev/block/by-name/rawdump of="$out/rawdump-after.bin" bs=1048576 skip=288 count=2 2>"$out/rawdump-after-dd.txt"
sha256sum "$out"/rawdump-*.bin > "$out/rawdump-hashes.txt"
cleanup
trap - EXIT
echo completed > "$out/status"
