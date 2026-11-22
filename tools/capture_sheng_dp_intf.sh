#!/system/bin/sh
# Bounded SDE-side DP interface readback, not a DP packet/wire capture.
# sde_dbg.c: *_off changes only the software read selector; never write *_reg.
# sde_hw_intf.c: 0x000..0x06c are timing/config controls, 0x090 panel format.
# Do not expand to interrupt, MISR, or whole-bank dump registers.
set -eu
[ "$(id -u)" = 0 ] || exit 1
dt=/sys/firmware/devicetree/base/soc/qcom,mdss_mdp@ae00000
debug=/sys/kernel/debug/dri/0/debug
offsets=$(od -An -tx1 "$dt/qcom,sde-intf-off" | tr -d ' \n\r')
types=$(od -An -tx1 "$dt/qcom,sde-intf-type" | tr -d ' \n\r')
[ "$offsets" = 00035000000360000003700000038000 ] || exit 2
[ "$types" = 6470006473690064736900647000 ] || exit 2
old=$(cat "$debug/sde_off")
set -- $old
# Reader prints a padded 0x offset; writer uses %6x, so normalize it first.
restore=$(printf '%x %x' "$((0x${1#0x}))" "$((0x${2#0x}))")
# Restore the pre-existing debug selector even on interrupted captures.
trap 'printf "%s\n" "$restore" > "$debug/sde_off"' EXIT
trap 'exit 130' INT TERM HUP
printf 'uptime: '; cat /proc/uptime
printf 'dt_offsets_be=%s\ndt_types_hex=%s\noriginal_selector=%s\n' "$offsets" "$types" "$old"
cat /sys/kernel/debug/drm_dp/dp_debug
for base in 35000 38000; do
    printf '\n=== DP INTF base 0x%s timing/config ===\n' "$base"
    printf '%s 70\n' "$base" > "$debug/sde_off"
    timeout 3 cat "$debug/sde_reg"
    panel=$(printf '%x' "$((0x$base + 0x90))")
    printf '\n=== DP INTF panel format ===\n'
    printf '%s 4\n' "$panel" > "$debug/sde_off"
    timeout 3 cat "$debug/sde_reg"
done
