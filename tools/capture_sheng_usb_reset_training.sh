#!/system/bin/sh
# Bounded sheng-only diagnostic: sample existing debugfs and reset the gadget once.
# No direct PHY/register/role/function/partition writes. The standard Android
# reset request itself may disconnect ADB; run with nohup and tablet-local output.
set -eu
[ "${1:-}" = --reset-once ] || { echo 'usage: sh capture_sheng_usb_reset_training.sh --reset-once'; exit 2; }
[ "$(getprop ro.product.device)" = sheng ]
[ "$(getprop ro.serialno)" = ca10ede3 ]
[ "$(id -u)" = 0 ]
reg=/sys/kernel/debug/usb/a600000.dwc3/regdump
[ -r "$reg" ]
umask 077
d=/data/local/tmp/sheng-usb-training-$(date +%Y%m%d-%H%M%S)-$$
mkdir "$d"
echo "$d"
exec >"$d/status" 2>&1
cat /proc/sys/kernel/random/boot_id > "$d/boot-before.txt"
svc usb getFunctions > "$d/functions-before.txt"
tr=/sys/kernel/tracing/instances/sheng_training_$$
own=0; sampler=''
cleanup() {
    if [ -n "$sampler" ]; then kill "$sampler" 2>/dev/null || :; wait "$sampler" 2>/dev/null || :; fi
    if [ "$own" = 1 ]; then
        echo 0 > "$tr/tracing_on"
        cat "$tr/trace" > "$d/controller.trace"
        rmdir "$tr" || echo trace_cleanup_failed
    fi
}
trap cleanup EXIT
trap 'exit 3' HUP INT TERM
mkdir "$tr"; own=1
echo 0 > "$tr/tracing_on"
echo 128 > "$tr/buffer_size_kb"
for event in dwc3_readl dwc3_writel; do
    # Offsets are the unadjusted SNPS offsets, verified in the matching io.h.
    echo 'offset == 0xc700 || offset == 0xc704 || offset == 0xc708 || offset == 0xc70c || offset == 0xc2c0' > "$tr/events/dwc3/$event/filter"
    echo 1 > "$tr/events/dwc3/$event/enable"
done
echo 'event & 1' > "$tr/events/dwc3/dwc3_event/filter"
echo 1 > "$tr/events/dwc3/dwc3_event/enable"
echo 1 > "$tr/tracing_on"
dmesg > "$d/kernel-before.txt"
(
    i=0
    while [ "$i" -lt 120 ]; do
        read -r t _ < /proc/uptime
        echo "SAMPLE $i $t"
        timeout 2 cat "$reg" | grep -E '^(GDBGLTSSM|DCFG|DCTL|DSTS|GUSB3PIPECTL\(0\)) ='
        read -r t _ < /proc/uptime
        echo "SAMPLE_END $i $t"
        i=$((i+1))
        # Best-effort cadence only; register reads and shell startup add latency.
        sleep 0.05
    done
) > "$d/register-samples.txt" 2>&1 &
sampler=$!
sleep 0.5
read -r t _ < /proc/uptime
echo "reset_request $t"
timeout 10 svc usb resetUsbGadget > "$d/reset-command.txt" 2>&1
read -r t _ < /proc/uptime
echo "reset_command_returned $t"
wait "$sampler"; sampler=''
dmesg > "$d/kernel-after.txt"
timeout 3 cat /sys/kernel/debug/ipc_logging/a600000.ssusb/log > "$d/controller-ipc.txt" || :
cat /proc/sys/kernel/random/boot_id > "$d/boot-after.txt"
svc usb getFunctions > "$d/functions-after.txt"
cat /sys/class/udc/a600000.dwc3/current_speed > "$d/speed-after.txt"
cat /sys/class/udc/a600000.dwc3/state > "$d/udc-after.txt"
echo finished
