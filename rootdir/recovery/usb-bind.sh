#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
# One conditional bind, not a USB reset/retry loop. Common Recovery still owns
# gadget construction, FunctionFS and configuration changes.
exec >> /dev/sheng-recovery-usb.log 2>&1
[ "$(getprop ro.product.device)" = sheng ] || exit 1
[ "$(getprop vendor.sheng.recovery.usb_role_ready)" = 1 ] || exit 1
[ "$(getprop sys.usb.configfs)" = 1 ] || exit 1
[ "$(getprop sys.usb.ffs.ready)" = 1 ] || exit 1
controller=$(getprop sys.usb.controller)
[ "$controller" = a600000.dwc3 ] || exit 1
[ -r "/sys/class/udc/$controller/state" ] || exit 1
config=$(getprop sys.usb.config)
case "$config" in
    adb|sideload) function=ffs.adb ;;
    fastboot) function=ffs.fastboot ;;
    *) exit 1 ;;
esac
gadget=/config/usb_gadget/g1
bound=$(cat "$gadget/UDC") || exit 1
if [ "$bound" = "$controller" ]; then
    echo "Gadget already bound to $controller; no change"
    exit 0
fi
[ -z "$bound" ] || exit 1
# Never bind a gadget while the common action is tearing down/replacing f1.
target=$(readlink -f "$gadget/configs/b.1/f1") || exit 1
[ "$target" = "$gadget/functions/$function" ] || exit 1
[ "$(getprop sys.usb.config)" = "$config" ] || exit 1
[ "$(getprop sys.usb.ffs.ready)" = 1 ] || exit 1
if echo "$controller" > "$gadget/UDC"; then
    echo "Deferred $config gadget bound to $controller after UDC publication"
else
    echo "Deferred $config gadget bind failed; preserving state without retry"
    exit 1
fi
