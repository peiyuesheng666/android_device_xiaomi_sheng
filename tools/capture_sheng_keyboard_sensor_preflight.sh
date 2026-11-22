#!/system/bin/sh
# Read-only prerequisite capture. Never stop services, unload modules or write calibration.
set -eu
test "$(getprop ro.serialno)" = ca10ede3 || {
  echo 'REFUSED: not the 6.18 target' >&2
  exit 1
}
case "$(uname -r)" in
  6.18.*) ;;
  *) echo 'REFUSED: unexpected kernel' >&2; exit 1 ;;
esac
echo '=== IDENTITY ==='
id
uname -r
getprop sys.boot_completed
getenforce
echo '=== KEYBOARD MODULE REFERENCES ==='
grep -E '^nanosic_driver ' /proc/modules || true
if [ -r /sys/module/nanosic_driver/refcnt ]; then
  cat /sys/module/nanosic_driver/refcnt
fi
ls /sys/module/nanosic_driver/holders 2>/dev/null || true
echo '=== RELATED SERVICES ==='
getprop | grep -Ei 'init.svc.*(sensor|nano|keyboard)' || true
ps -A | grep -Ei 'sensor|nanoapp|keyboard' || true
echo '=== LEGACY SENSOR INIT CALLS (NOT CALIBRATION CONTENTS) ==='
for directory in /vendor/etc/init /odm/etc/init /system_ext/etc/init; do
  test -d "$directory" || continue
  grep -nE 'sheng.sensor.frame|sheng-sensor-frame|migrate-landscape-frame|prepare-isolated-frame|verify-isolated-frame|restore_xiaomi_sensor_frame|Restore-Xiaomi-Sensors' \
    "$directory"/*.rc 2>/dev/null || true
done
echo '=== SENSOR HAL FILE IDENTITIES ==='
for path in /vendor/bin/hw/android.hardware.sensors-service.sheng-multihal \
            /vendor/etc/init/android.hardware.sensors-service.sheng-multihal.rc \
            /vendor/etc/init/vendor.sensors.sscrpcd.rc; do
  test ! -f "$path" || sha256sum "$path"
done
echo 'READ_ONLY_PREFLIGHT_COMPLETE'
