#!/system/bin/sh
# Debug convenience only; preserve Android's existing ADB authentication.
i=0
while [ "$(getprop sys.boot_completed)" != 1 ] && [ "$i" -lt 120 ]; do
    sleep 2
    i=$((i + 1))
done
setprop service.adb.tcp.port 5555
setprop ctl.restart adbd
