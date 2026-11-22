# Cold-entry fastbootd trace candidate

This is **opt-in diagnostic source, not a production default**. It is not wired
into device.mk. The offline candidate pair is qualified in
`reports/sheng-fastbootd-cold-package-20261119/qualification.json`. Subsequent
deployment and one actual cold-entry trace are recorded in
`reports/sheng-fastbootd-cold-runtime-20261119-231107/summary.json`.
Recovery execution and same-boot ADB return/export passed; the original timeout
did NOT reproduce. Neither the original fault's cause nor a fix is established.

Subsequent loaded-module audit found that recovery_b overrides six module files
from vendor_boot, including all three repaired USB drivers. The observer runs,
but the USB3 repair is NOT active in that Recovery module set. See
`reports/sheng-fastbootd-bootloader-entry-20261119/loaded-recovery-vs-vendor-usb-modules.json`.
The vendor image's correct module hashes alone cannot qualify live Recovery
module parity. This gate must use actual loaded notes/root-file hashes.

The already-tested warm logger starts through ADB, too late to observe a cold
entry. This candidate starts independently as an init service on `post-fs`,
before the common Recovery `boot` action starts the recovery service. The
platform files under bootable/recovery and system/core remain unchanged.

For a separately reviewed candidate, copy the RC into Recovery's
`system/etc/init/` and capture.sh to `system/bin/sheng-fastboot-cold-trace`.
The RC invokes sh explicitly, so the script itself need not be executable.
The append-only builder is `scripts/build_sheng_fastbootd_cold_trace.py`; run it
under WSL with `--workspace`, `--host-bin` and a new `--out` directory. It keeps
unpack scratch on Linux because unpack_bootimg's metadata symlinks may fail on
DrvFS. Images and logs may be placed on E:. The builder never flashes anything.
Use matching kernel/modules and `sheng_bootlog.enable=0`. Enable only in the
candidate boot config with `androidboot.sheng_fastboot_trace=1`; optionally add
`androidboot.sheng_fastboot_trace_return_adb=1` for a post-capture Recovery UI
socket request to restore ADB. Do not change vbmeta or production defaults as a
shortcut. Verify the exact unpacked ramdisk and AVB metadata before any flash.

The script guards serial ca10ede3, sheng, slot _b, root, Recovery executable,
force_normal_boot, the opt-in property, rawdump preservation and tmpfs /tmp.
It refuses to overwrite its boot-ID-specific output. It samples for up to 120
seconds / 60 iterations (sysfs/task reads have timeouts); init adds a
180-second timeout wrapper. Kernel uninterruptible waits can defeat userspace
timeouts. A timeout or incomplete status is NOT a successful capture.
There are no direct PHY, role, partition or mount writes, and no automatic
reboot. The optional ADB-return request happens only after evidence capture.

Read /tmp/sheng-fastbootd-cold-BOOT_ID/ before any reboot. Tmpfs evidence cannot
survive a kernel crash or a manual reboot. Keep the separate preserve-rawdump
path for previous failure evidence; this observer intentionally does not write
rawdump. It captures start/end dmesg snapshots, not an unlimited dmesg stream;
heavy ring-buffer turnover can lose intervening events.

The `start` action is asynchronous: source ordering alone does not prove the
worker actually ran before the first USB transition. Check captured uptimes
against the controller and Recovery logs in a real cold boot.

The first deployed candidate ran with rootfs file labels under the existing
Recovery policy, before USB attachment. No SELinux policy workaround was added.
It sampled a high-speed fastbootd link and successfully returned to ADB after
capture. ADB needed one `adb root` restart to read root-only tmpfs logs; the
kernel boot ID remained unchanged.

Remaining: reproduce the original host timeout and correlate failure traces,
broader cold-entry regression testing, and Android acceptance of the diagnostic
pair. A single passing instrumented entry is not proof of a fix. Use
`scripts/capture_sheng_recovery_trace.py` for guarded same-boot export; it accepts
ADB's `recovery` state and avoids Windows Unicode `adb pull` path failures.
