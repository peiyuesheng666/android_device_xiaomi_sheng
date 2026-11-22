#!/system/bin/sh
set -eu
D=/data/adb/modules/sheng_adb_tcp5555
mkdir -p "$D"
cp /data/local/tmp/sheng_adb_tcp5555/module.prop "$D/module.prop"
cp /data/local/tmp/sheng_adb_tcp5555/service.sh "$D/service.sh"
chown -R 0:0 "$D"
chmod 0755 "$D" "$D/service.sh"
chmod 0644 "$D/module.prop"
echo "AUTH: $(getprop ro.adb.secure)"
echo "PORT BEFORE: $(getprop service.adb.tcp.port)"
setprop service.adb.tcp.port 5555
setprop ctl.restart adbd
