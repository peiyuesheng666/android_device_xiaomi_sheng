#!/system/bin/sh
set -eu
test "$(id -u)" = 0
test "$(getprop ro.boot.serialno)" = ca10ede3
t=/sys/kernel/debug/tracing
g=sheng_dp_$$
o=$(mktemp -d /data/local/tmp/sheng-dp-config-XXXXXX)
i=$t/instances/$g
cleanup() {
 echo 0 > "$i/tracing_on" 2>/dev/null || true
 echo 0 > "$i/events/$g/enable" 2>/dev/null || true
 cat "$i/trace" > "$o/config-trace.txt" 2>/dev/null || true
 rmdir "$i" 2>/dev/null || true
 for e in ctrl msa msa420 msa500 misc vsc hw_write; do echo "-:$g/$e" >> "$t/kprobe_events" 2>/dev/null || true; done
 chmod -R a+rX "$o"
}
trap cleanup EXIT HUP INT TERM
mkdir "$i"
echo 256 > "$i/buffer_size_kb"
printf 'p:%s/ctrl msm_drm:dp_catalog_panel_config_ctrl cfg=%%x1:u32\n' "$g" >> "$t/kprobe_events"
printf 'p:%s/msa msm_drm:dp_catalog_panel_config_msa rate=%%x1:u32 pclk=%%x2:u32\n' "$g" >> "$t/kprobe_events"
printf 'p:%s/misc msm_drm:dp_catalog_panel_config_misc\n' "$g" >> "$t/kprobe_events"
printf 'p:%s/msa500 msm_drm:dp_catalog_panel_config_msa_v500 rate=%%x1:u32 pclk=%%x2:u32\n' "$g" >> "$t/kprobe_events"
printf 'p:%s/msa420 msm_drm:dp_catalog_panel_config_msa_v420 rate=%%x1:u32 pclk=%%x2:u32\n' "$g" >> "$t/kprobe_events"
# ARM64 source ABI: four u32s + two pointers = offset32 for VSC header.
# Packed dp_sdp_header is4bytes, so payload DB16..18 are offsets52..54.
# These are software input bytes, NOT MMIO or a captured on-wire packet.
printf 'p:%s/vsc msm_drm:dp_catalog_panel_setup_vsc_sdp hb1=+33(%%x0):u8 hb2=+34(%%x0):u8 hb3=+35(%%x0):u8 db16=+52(%%x0):u8 db17=+53(%%x0):u8 db18=+54(%%x0):u8\n' "$g" >> "$t/kprobe_events"
# ARM64 dp_write_hw(catalog, io_data, offset, value); dp_io_data.name is
# its first pointer. Observe existing writes, without extra MMIO access.
# This is write-entry/order evidence, NOT posted-write completion/readback.
printf 'p:%s/hw_write msm_drm:dp_write_hw bank=+0(+0(%%x1)):string off=%%x2:u32 val=%%x3:u32\n' "$g" >> "$t/kprobe_events"
echo '(bank == "dp_link" && (off == 0 || off == 4 || off == 8 || off == 16 || off == 24 || (off >= 28 && off <= 52) || off == 76 || off == 552 || off == 556 || off == 588 || (off >= 768 && off <= 804))) || (bank == "dp_p0" && (off == 16 || off == 20 || off == 136))' > "$i/events/$g/hw_write/filter"
cat /sys/kernel/debug/drm_dp/dp_debug > "$o/before.txt"
echo 1 > "$i/events/$g/enable"
echo 1 > "$i/tracing_on"
echo "capture=$o"
# Optional bounded duration permits a short probe/cleanup smoke test.
duration=${1:-120}
case "$duration" in 5|30|60|120) ;; *) exit 2 ;; esac
sleep "$duration"
cat /sys/kernel/debug/drm_dp/dp_debug > "$o/after.txt"
