#!/usr/bin/env python3
"""Package a reversible, device-pinned composer trial; does not deploy or flash."""
import argparse
import hashlib
from pathlib import Path
import zipfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--binary', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
binary = a.binary.read_bytes()
if binary[:5] != b'\x7fELF\x02' or binary[18:20] != b'\xb7\x00':
    p.error('Expected a 64-bit AArch64 ELF')
digest = hashlib.sha256(binary).hexdigest()
baseline = '4f718bff07925e718fabfbc01d8fb2839ffaaa2aa467b0ee51edbe34620cd2a3'
if digest == baseline:
    p.error('Candidate is the unchanged live baseline')
script = '''#!/system/bin/sh
# Temporary deployment only: disable module + reboot restores the original.
MODDIR=${0%/*}
TARGET=/vendor/bin/hw/vendor.qti.hardware.display.composer-service-sheng
LOG="$MODDIR/trial.log"
exec >>"$LOG" 2>&1
echo "trial boot $(cat /proc/sys/kernel/random/boot_id)"
[ "$(getprop ro.boot.serialno)" = ca10ede3 ] || exit 1
[ "$(getprop ro.boot.slot_suffix)" = _b ] || exit 1
check_hash() { [ "$(sha256sum "$1" | cut -d ' ' -f1)" = "$2" ]; }
check_hash "$MODDIR/composer" CANDIDATE_SHA || exit 1
check_hash "$TARGET" BASELINE_SHA || exit 1
chown 0:2000 "$MODDIR/composer" || exit 1
chmod 0755 "$MODDIR/composer" || exit 1
chcon u:object_r:hal_graphics_composer_default_exec:s0 "$MODDIR/composer" || exit 1
/system/bin/nsenter -t 1 -m -- /system/bin/mount --bind "$MODDIR/composer" "$TARGET" || exit 1
echo 'composer trial bind installed in PID1 mount namespace'
'''.replace('CANDIDATE_SHA', digest).replace('BASELINE_SHA', baseline)
files = {
    'module.prop': ('id=sheng_dp_composer_trial\nname=Sheng DP composer geometry trial\n'
                    'version=20261122\nversionCode=20261122\nauthor=sheng\n'
                    'description=Temporary geometry fix; disable and reboot to roll back.\n'),
    'skip_mount': '',
    'customize.sh': ('#!/system/bin/sh\n'
                     '[ "$(getprop ro.boot.serialno)" = ca10ede3 ] || abort "Wrong device"\n'
                     '[ "$(getprop ro.boot.slot_suffix)" = _b ] || abort "Wrong slot"\n'
                     'set_perm "$MODPATH/post-fs-data.sh" 0 0 0755\n'
                     'set_perm "$MODPATH/composer" 0 2000 0755 u:object_r:hal_graphics_composer_default_exec:s0\n'),
    'post-fs-data.sh': script,
    'candidate.sha256': digest + '\n',
}
a.out.parent.mkdir(parents=True, exist_ok=True)
with a.out.open('xb') as output, zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
    for name, data in files.items():
        z.writestr(name, data)
    z.writestr('composer', binary)
print(f'{a.out}: composer SHA-256 {digest}')
