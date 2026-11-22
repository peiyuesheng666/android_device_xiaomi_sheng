#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Read-only state probe. Missing nodes and permission failures are evidence.
section() { printf '\n===== %s =====\n' "$1"; }
section identity
date; cat /proc/uptime; id; uname -a; getenforce
section usb-properties
getprop | grep -iE 'usb|typec|displayport|build.fingerprint|build.version|product.device|boot.slot|boot.bootreason|boot.hardware'
section usb-speed-role-and-phy
for d in /sys/bus/usb/devices/* /sys/class/udc/* /sys/class/usb_role/* /sys/class/typec/* /sys/class/dual_role_usb/* /sys/bus/platform/devices/*dwc* /sys/bus/platform/devices/*usb* /sys/bus/platform/devices/*ssphy* /sys/bus/platform/devices/*hsphy*; do
    [ -e "$d" ] || continue
    echo "DEVICE: $d"; readlink -f "$d/driver"
    for n in speed version idVendor idProduct manufacturer product bcdUSB bcdDevice busnum devnum authorized state current_speed maximum_speed function role mode data_role power_role port_type preferred_role power_operation_mode vconn_source supports_usb_power_delivery usb_power_delivery_revision uevent power/runtime_status power/control; do
        [ -e "$d/$n" ] || continue
        echo "FILE: $d/$n"; cat "$d/$n"
    done
done
section gadget
for d in /config/usb_gadget/*; do
    [ -d "$d" ] || continue
    ls -l "$d" "$d/configs" "$d/functions"; cat "$d/UDC"
    for c in "$d"/configs/*; do [ -d "$c" ] && ls -l "$c"; done
done
section typec-extcon-and-power
for d in /sys/class/extcon/* /sys/class/power_supply/*; do
    [ -d "$d" ] || continue
    for n in name state uevent; do [ ! -e "$d/$n" ] || { echo "FILE: $d/$n"; cat "$d/$n"; }; done
done
section charging-protocol-and-limits
for d in /sys/class/power_supply/* /sys/class/qcom-battery/*; do
    [ -d "$d" ] || continue
    for n in real_type usb_type charge_type quick_charge_type pd_active pd_current_max pd_voltage_max input_current_limit input_current_limited current_max voltage_max constant_charge_current_max constant_charge_voltage_max current_now voltage_now power_now capacity temp status health charging_enabled charge_enabled battery_charging_enabled input_suspend thermal_input_current_limit charge_control_limit charge_control_limit_max fastcharge_mode apdo_max adapter_id adapter_svid adapter_power_max cp_ibus cp_vbus ibus vbus; do
        [ ! -e "$d/$n" ] || { echo "FILE: $d/$n"; cat "$d/$n"; }
    done
done
section thermal-zones
for d in /sys/class/thermal/thermal_zone*; do
    [ -d "$d" ] || continue
    echo "ZONE: $d"; cat "$d/type" "$d/temp"
done
section display-connectors
for d in /sys/class/drm/card*-*; do
    [ -d "$d" ] || continue
    echo "CONNECTOR: $d"
    for n in status enabled modes link_status; do [ ! -e "$d/$n" ] || { echo "FILE: $n"; cat "$d/$n"; }; done
    if [ -r "$d/edid" ]; then echo EDID_HEX; od -An -tx1 -v "$d/edid"; fi
done
section kernel-debug-status
for p in /sys/kernel/debug/usb/devices /sys/kernel/debug/devices_deferred /sys/kernel/debug/dri/0/state /sys/kernel/debug/dri/1/state; do
    [ ! -e "$p" ] || { echo "FILE: $p"; cat "$p"; }
done
exit 0
