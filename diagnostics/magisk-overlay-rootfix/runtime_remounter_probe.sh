#!/system/bin/sh
# Recovery only, isolated mount namespace; never operates on real /system.
set -eu
base="$1"
oldns="$2"
[ "$(readlink /proc/self/ns/mnt)" != "$oldns" ] || exit 80
mount -o rprivate none /
mount -t tmpfs -o size=8m,mode=0700 sheng-remounter-probe "$base"
for variant in control linked deleted directory; do
    root="$base/$variant"
    mkdir -p "$root/system/bin" "$root/upper" "$root/work" "$root/holder"
    if [ "$variant" = directory ]; then
        mkdir "$root/source" "$root/system/bin/init" "$root/holder/init"
        printf ORIGINAL_BIND > "$root/source/value"
    else
        printf ORIGINAL_BIND > "$root/source"
        printf LOWER_INIT > "$root/system/bin/init"
        : > "$root/holder/init"
    fi
    options="lowerdir=$root/system,upperdir=$root/upper,workdir=$root/work"
    mount -t overlay overlay -o "$options" "$root/system"
    echo "CASE=$variant"
    if [ "$variant" = control ]; then
        umount "$root/system"
        echo 'result=no_child_unmount_passed'
        continue
    fi
    mount -o bind "$root/source" "$root/system/bin/init"
    [ "$variant" != deleted ] || rm "$root/source"
    inode=$(stat -c %i "$root/system/bin/init")
    # Exact failing syscall in the stock overlay_remounter: no lazy detach.
    if umount "$root/system"; then
        echo 'ERROR=unexpected_unmount_with_child'
        exit 81
    fi
    grep " $root/system/bin/init " /proc/self/mountinfo
    [ "$(stat -c %i "$root/system/bin/init")" = "$inode" ] || exit 82
    echo 'result=stock_unmount_rejected_child_bind_preserved'
    # Exercise the required transaction, NOT a production implementation.
    mount -o move "$root/system/bin/init" "$root/holder/init"
    umount "$root/system"
    mount -t overlay overlay -o "$options" "$root/system"
    mount -o move "$root/holder/init" "$root/system/bin/init"
    [ "$(stat -c %i "$root/system/bin/init")" = "$inode" ] || exit 83
    if [ "$variant" = directory ]; then value=$(cat "$root/system/bin/init/value"); else value=$(cat "$root/system/bin/init"); fi
    [ "$value" = ORIGINAL_BIND ] || exit 84
    grep " $root/system .* - overlay " /proc/self/mountinfo
    echo 'result=move_out_remount_restore_passed overlay_retained=true inode_preserved=true'
done
echo ALL_CASES_PASSED
