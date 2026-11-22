# r61 tap capability and suspend statistics batch

2026-11-12: installed and verified on ca10ede3 A over Android r53, retaining
the independently accepted Recovery r59 and SELinux Enforcing. The user
confirmed that double-tap wake still works after this update.

The two independent fixes are recorded in
[SENSOR_GESTURE_CAPABILITIES.md](SENSOR_GESTURE_CAPABILITIES.md) and
[SUSPEND_WAKEUP_STATS.md](SUSPEND_WAKEUP_STATS.md). Their scoped source commits
are `8f006cc` and `90818c1`. Standard double-tap wake still uses the existing
device-owned THP mode-14 backend.

The QTI candidate failed process teardown after successfully enumerating 19
components. Its exact diagnosis and limits are in
[`interfaces/compat/codec2/README-qti.md`](../interfaces/compat/codec2/README-qti.md).
r61 excludes that executable replacement. The r53 QTI executable is preserved
from the sealed baseline filesystem and its hash is checked after staging,
before flashing and during runtime verification. No diagnostic probe result
can qualify a QTI replacement unless sandboxing and full process teardown pass.

## Build and packaging

Use the normal scoped build helper `tools/build_sheng_device_continue_r60.sh`.
Its name retains the original investigation batch; r61 consumes only the
configuration outputs. A valid build needs the normal success marker,
matching source mirror and a fresh upstream audit. The helper's final success
receipt now additionally requires its postbuild checks to have completed;
an early clean exit cannot alone report success.

Package in a UTF-8 environment (`LANG=C.UTF-8 LC_ALL=C.UTF-8`) with
`tools/package_sheng_device_continue_r60.py --configuration-only`
and the required workspace, build-log, audit, mirror and work arguments.
The exact changed vendor paths are `build.prop`, `etc/init/init.sm8550.rc`,
and `etc/selinux/vendor_sepolicy.cil`; the sole ODM change is the framework
overlay APK. Existing resource identities and APK signing must match, with
exactly the two unavailable tap-sensor resource changes. Policy must add only
the four observed genfs mappings, with no new allow rules. Actual combined
partition policy, neverallows, filesystem metadata and full AVB chain are
verified before publication to `artifacts/system-hardware-followup-sheng-r61`.

`tools/flash_sheng_device_continue_r60.ps1 -Revision 61` performs read-only
package/baseline validation by default. `-Flash` writes only ODM A, vendor A
and vbmeta A after exact baseline and boot-dependency checks. Announce the
operation before using that switch. Recovery and boot are retained dependencies.

## Runtime acceptance

After installation, run `tools/verify_sheng_device_continue_r61.py` with the
workspace and a new output directory. It checks the actual installed partition
hashes, original SystemUI and QTI identities, properties, effective overlay
resources and SensorService registrations. It verifies labels on all ten
statistic attributes of every discovered instance beneath the four observed
wakeup parents, preserving the FPC device-control label.

The verifier asks `suspend_control_internal` for real statistics and checks
that all five baseline wakeup names appear, with no fresh system_suspend AVC
or read-permission error. This must pass in Enforcing. Physical double-tap wake
and fingerprint authentication after prolonged standby remain distinct tests;
automated statistics access does not establish either functional result.

## Installed results

Normal scoped module/policy build, 24-input source mirror and fresh audit of
all 1,243 repo-managed projects passed. The completed receipt is
`r60-20261112-121037-N4gXWk` beneath the WSL device-continue build directory.
The initial build wrapper failed after its successful module build when its
running script was edited; the stable rerun completed all postbuild checks.

The delivered images passed exact filesystem/content/metadata checks, actual
combined boot-policy compilation with neverallows, and full AVB verification.
Only three vendor files and the ODM framework overlay changed. Preflight
verification additionally binds the unchanged system image to the accepted
r38 restore receipt and reads that logical partition through its mapper.
Valid receipts passed; altered system identity, an enabled QTI candidate,
a missing boot dependency and an extra overlay change were all rejected.

| Installed A-slot image | SHA-256 |
| --- | --- |
| vendor | `776ea31a393986ac6c6657a463e0277867380cc49ff4fb26e803b2d2a7b0b3cd` |
| odm | `12ea70b902ece536aa7fac85ccd0d281eec448d2a2d39a711c1831208e38f91e` |
| vbmeta | `af0685cbc26ff09f14d17d829fe036fd2636d98224d1c9522ad24cd53893fd89` |

After boot, all 14 declared partition/dependency hashes matched. The five
observed wakeup instances expose all 50 statistic files as `sysfs_wakeup`,
with the FPC device-control label retained. `suspend_control_internal` reports
all five names without fresh related read errors or AVCs. The two unavailable
tap sensors are absent from SensorService; both effective Doze strings are
empty and standard double-tap wake remains enabled. The user answered
“可以正常双击亮屏”.

The device retains 144/144 refresh settings and high-report property 1;
touch, keyboard and both Codec2 services are running. The current boot's crash
buffer is empty. This one clean boot does not establish a fix for the earlier
Dolby startup failure. Long-standby fingerprint, full product and wider media
validation remain open.

Evidence is in workspace `reports/device/20261112-device-continue/`:
`r61-normal-build-status.json`, `r61-source-mirror.json`,
`r61-upstream-audit.json`, `r61-manifest-guard-tests.json`,
`r61-runtime/runtime.json`, `r61-user-acceptance.json`, and the flash/boot logs.
The automated receipt intentionally leaves physical-test fields false; the
separate user receipt records the subsequent real double-tap acceptance.
Storage preparation and its remaining E-drive files are documented in
[PACKAGING_STORAGE_20261112.md](PACKAGING_STORAGE_20261112.md).
