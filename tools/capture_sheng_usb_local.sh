#!/system/bin/sh
# One finite capture on the tablet. No gadget, role, PHY or partition writes.
umask 077
[ "$(getprop ro.product.device)" = sheng ] && [ "$(id -u)" = 0 ] || exit 1
seconds=${1:-360}; case "$seconds" in ''|*[!0-9]*) exit 2;; esac
[ "$seconds" -ge 10 ] && [ "$seconds" -le 600 ] || exit 2
d=/data/local/tmp/sheng-usb-$(date +%Y%m%d-%H%M%S)-$$; mkdir "$d" || exit 1
echo "$d"; exec >"$d/status" 2>&1; echo "pid=$$ seconds=$seconds"; cat /proc/sys/kernel/random/boot_id
tr=/sys/kernel/tracing/instances/sheng_usb_$$; own=0
cleanup(){ if [ "$own" = 1 ]; then echo 0 > "$tr/tracing_on"; cat "$tr/trace" > "$d/controller.trace"; rmdir "$tr" || echo trace_cleanup_failed; fi; }
trap cleanup EXIT
trap 'exit 3' HUP INT TERM
snapshot(){ dmesg | grep -Ei 'dwc3|PS5169|ssphy|USB_STATE|msm_eusb|ucsi|USB disconnect' | grep -v 'Modules linked in:' | tail -1000 > "$d/$1-kernel.txt"; timeout 3 cat /sys/kernel/debug/ipc_logging/a600000.ssusb/log > "$d/$1-controller.txt"; }
if mkdir "$tr"; then own=1; echo 0 > "$tr/tracing_on"; echo 128 > "$tr/buffer_size_kb"; if echo 'event & 1' > "$tr/events/dwc3/dwc3_event/filter" && echo 1 > "$tr/events/dwc3/dwc3_event/enable" && echo 1 > "$tr/tracing_on"; then echo private_device_events_enabled; else echo trace_setup_incomplete; fi; fi
snapshot before
readval(){ v=''; if [ -r "$1" ]; then read -r v < "$1"; fi; printf '%s' "${v:-NA}"; }
printf 'uptime_s\tudc_state\tspeed\tcc\tdwc_link\tgadget_udc\n' > "$d/link.tsv"
read -r t _ < /proc/uptime; end=$((${t%.*}+seconds)); last=''
while :; do read -r t _ < /proc/uptime; [ "${t%.*}" -lt "$end" ] || break
 state="$(readval /sys/class/udc/a600000.dwc3/state)"; speed="$(readval /sys/class/udc/a600000.dwc3/current_speed)"; cc="$(readval /sys/class/qcom-battery/cc_orientation)"; link="$(readval /sys/kernel/debug/usb/a600000.dwc3/link_state)"; bound="$(readval /config/usb_gadget/g1/UDC)"
 printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$t" "$state" "$speed" "$cc" "$link" "$bound" >> "$d/link.tsv"
 if [ "$state/$speed/$bound" != "$last" ]; then echo "transition $t $state $speed $bound"; last="$state/$speed/$bound"; fi
 sleep 1
done
snapshot after; echo finished
