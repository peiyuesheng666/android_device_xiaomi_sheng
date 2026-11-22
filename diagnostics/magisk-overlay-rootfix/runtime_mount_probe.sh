#!/system/bin/sh
# Run ONLY as child of unshare -m; all mounts are private and ephemeral.
set -eu
base="$1"
oldns="$2"
[ "$(readlink /proc/self/ns/mnt)" != "$oldns" ] || exit 80
mount -o rprivate none /
mount -t tmpfs -o size=8m,mode=0700 sheng-rootfix-probe "$base"
for variant in linked deleted directory shared-linked shared-deleted mismatch; do
    root="$base/$variant"
    mkdir -p "$root/system/bin" "$root/upper" "$root/work" "$root/holder"
    if [ "$variant" = directory ]; then
        mkdir "$root/source" "$root/system/bin/init" "$root/holder/init"
        printf MAGISK_INIT > "$root/source/value"
        printf ANDROID_INIT > "$root/system/bin/init/value"
    else
        printf MAGISK_INIT > "$root/source"
        printf ANDROID_INIT > "$root/system/bin/init"
        if [ "$variant" = mismatch ]; then mkdir "$root/holder/init"; else : > "$root/holder/init"; fi
    fi
    mount -o bind "$root/source" "$root/system/bin/init"
    if [ "$variant" = deleted ] || [ "$variant" = shared-deleted ]; then rm "$root/source"; fi
    if [ "$variant" = shared-linked ] || [ "$variant" = shared-deleted ]; then
        mount -o bind "$root/holder" "$root/holder"
        mount -o shared none "$root/holder"
    fi
    inode=$(stat -c %i "$root/system/bin/init")
    echo "CASE=$variant original_inode=$inode"
    if mount -o move "$root/system/bin/init" "$root/holder/init"; then
        [ "$variant" != mismatch ] && [ "$variant" != shared-deleted ] || exit 81
        # Moving the source mount out of a shared parent is intentionally forbidden.
        if [ "$variant" = shared-linked ]; then mount -o rprivate none "$root/holder"; fi
        mount -t overlay overlay -o "lowerdir=$root/system,upperdir=$root/upper,workdir=$root/work" "$root/system"
        mount -o move "$root/holder/init" "$root/system/bin/init"
        [ "$(stat -c %i "$root/system/bin/init")" = "$inode" ] || exit 82
        if [ "$variant" = directory ]; then value=$(cat "$root/system/bin/init/value"); else value=$(cat "$root/system/bin/init"); fi
        [ "$value" = MAGISK_INIT ] || exit 83
        grep " $root/system .* - overlay " /proc/self/mountinfo
        echo 'result=move_restore_passed overlay_retained=true inode_preserved=true'
    else
        [ "$variant" = mismatch ] || [ "$variant" = shared-deleted ] || exit 84
        [ "$(stat -c %i "$root/system/bin/init")" = "$inode" ] || exit 85
        echo 'result=expected_rejection original_bind_preserved=true'
    fi
done
echo ALL_CASES_PASSED
