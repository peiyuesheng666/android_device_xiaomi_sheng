#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Preserve the BSP's oops logger without blocking first-stage storage probing.
exec >> /dev/sheng-recovery-late-modules.log 2>&1
if grep -q '^block2mtd ' /proc/modules; then
    echo 'block2mtd was already loaded'
    exit 0
fi
module_argument=
for argument in $(cat /proc/cmdline); do
    case "$argument" in
        block2mtd.block2mtd=*) module_argument=${argument#block2mtd.} ;;
    esac
done
if [ -z "$module_argument" ]; then
    echo 'No BSP block2mtd argument; skipping the optional oops logger'
    exit 0
fi
module_value=${module_argument#block2mtd=}
module_device=${module_value%%,*}
if [ ! -b "$module_device" ] ||
   [ "$(readlink -f "$module_device")" != "$(readlink -f /dev/block/by-name/oops)" ]; then
    echo 'BSP block2mtd device does not resolve to the oops partition'
    exit 1
fi
echo "late block2mtd start at $(cat /proc/uptime) with $module_argument"
/system/bin/insmod /lib/modules/block2mtd.ko "$module_argument"
module_result=$?
echo "late block2mtd exit $module_result at $(cat /proc/uptime)"
exit "$module_result"
