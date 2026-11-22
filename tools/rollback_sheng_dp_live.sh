#!/system/bin/sh
# Remove only our temporary composer bind; do not change partitions or modules.
set -eu
T=/vendor/bin/hw/vendor.qti.hardware.display.composer-service-sheng
test "$(id -u)" = 0
test "$(getprop ro.boot.serialno)" = ca10ede3
test "$(getprop ro.boot.slot_suffix)" = _b
line=$(nsenter -t 1 -m -- cat /proc/self/mountinfo | grep " $T " || true)
if [ -z "$line" ]; then
    echo "No temporary composer bind to remove"
    exit 0
fi
echo "$line" | grep -q ' /local/tmp/sheng-dp-retry/composer '
nsenter -t 1 -m -- umount -l "$T"
actual=$(nsenter -t 1 -m -- sha256sum "$T" | cut -d ' ' -f1)
test "$actual" = 4f718bff07925e718fabfbc01d8fb2839ffaaa2aa467b0ee51edbe34620cd2a3
setprop ctl.restart vendor.qti.hardware.display.composer
echo "Original composer restored; restart requested"
