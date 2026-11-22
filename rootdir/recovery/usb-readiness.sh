#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Wait asynchronously so init can still mount firmware/start ADSP in fs.
# Require a fresh nonzero firmware direction as well as the published owner.
exec >> /dev/sheng-recovery-usb.log 2>&1
echo "sheng recovery USB: waiting for CC provider"
read -r now rest < /proc/uptime
deadline=$((${now%.*}+8))
attempt=0
ready=0
while [ "$attempt" -lt 80 ]; do
    if [ "$(cat /sys/class/qcom-battery/sheng_usb_cc_owner_ready 2>/dev/null)" = 1 ]; then
        cc=$(timeout 1 cat /sys/class/qcom-battery/sheng_usb_cc_fresh_orientation 2>/dev/null)
        case "$cc" in
            1|2) ready=1; break ;;
        esac
    fi
    read -r now rest < /proc/uptime
    [ "${now%.*}" -lt "$deadline" ] || break
    sleep 0.1
    attempt=$((attempt+1))
done
if [ "$ready" = 1 ]; then
    echo "CC provider and fresh firmware CC$cc ready; enabling peripheral role"
else
    # Keep Recovery reachable if charger/DSP fails; not a USB3 success.
    echo "CC provider wait expired; enabling fallback USB without a direction guarantee"
fi
controller=$(getprop ro.boot.usb.dwc3_msm)
controller=${controller:-a600000.ssusb}
case "$controller" in a600000.ssusb) ;; *) echo "Unexpected controller: $controller"; exit 1 ;; esac
echo peripheral > "/sys/bus/platform/devices/$controller/mode" || exit 1
# mode_store queues asynchronous role work. A successful write does not yet
# mean usb_add_gadget_udc() has published a controller for configfs to bind.
attempt=0
while [ "$attempt" -lt 60 ]; do
    if [ -r /sys/class/udc/a600000.dwc3/state ]; then
        echo "Peripheral UDC published; allowing the deferred gadget bind"
        setprop vendor.sheng.recovery.usb_role_ready 1
        exit $?
    fi
    sleep 0.05
    attempt=$((attempt+1))
done
echo "Peripheral UDC publication timed out; not claiming role readiness"
exit 1
