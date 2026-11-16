#!/system/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Firmware is mounted read-only by init before ADSP is requested. Keep the
# mount independent of /vendor, which recovery may mount and unmount later.
exec >> /dev/sheng-recovery-hardware.log 2>&1
echo "sheng recovery hardware: $(date)"
if [ "$(cat /sys/module/firmware_class/parameters/path)" != /firmware/image ]; then
    echo "Firmware search path was not configured by init; ADSP not started"
    exit 1
fi
if [ ! -r /firmware/image/adsp.mdt ] || [ ! -r /firmware/image/adsp.b01 ]; then
    echo "ADSP firmware unavailable; not starting a partially supplied DSP"
    exit 1
fi
found_adsp=0
for remote in /sys/class/remoteproc/remoteproc*; do
    [ -r "$remote/name" ] || continue
    case "$(cat "$remote/name")" in
        *adsp*)
            found_adsp=1
            if [ "$(cat "$remote/state")" = offline ]; then
                echo start > "$remote/state" || exit 1
            fi
            echo "$remote: $(cat "$remote/state")"
            ;;
    esac
done
if [ "$found_adsp" -ne 1 ]; then
    echo "ADSP remote processor unavailable"
    exit 1
fi
