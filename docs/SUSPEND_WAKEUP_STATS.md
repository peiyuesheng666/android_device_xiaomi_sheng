# sheng wakeup statistics labels

2026-11-12 regression correction: r61's `/soc:fingerprint_fpc/wakeup` rule
also matches the sibling `wakeup_enable`, because genfscon uses character
prefixes. The earlier parent-directory check did not cover that control file.
The HAL's denied write caused FPC_ERROR_IO and HW_UNAVAILABLE during enrollment,
followed by an existing-session abort on retry. An exact `wakeup_enable` mapping
to `sysfs_fingerprint_sheng` is now in the device tree; no allow rule was added.
Temporary relabeling and a fingerprint-service restart restored real enrollment;
the user confirmed success and framework records one print and five successful
authentications, with the HAL death counter unchanged. The permanent r62 policy
and matching vbmeta were installed on A. Normal module build, actual combined
policy/neverallows, compiled genfs lookup, AVB and all 14 postboot hashes passed.
Enforcing runtime retains the exact control label and all five wakeup instances'
50 statistic labels; the real suspend service reads every instance. One print,
two successful authentications and zero HAL deaths are recorded after reboot,
and the user confirmed fingerprint works normally. Prolonged standby remains
unverified. See fingerprint-regression-20261112.md and workspace
reports/device/20261112-fingerprint-regression/r62-runtime/runtime.json.
The remaining text records the original r61 statistics acceptance, whose scope
does not establish preservation of this control node.

2026-11-12: installed and verified in r61 on ca10ede3 A with the retained
5.15.220 kernel and Recovery r59. The failure capture below is from r53.
All five actual wakeup instances and 50 statistic files now have the intended
labels; the real suspend service reads and reports their statistics in Enforcing.

## Observed failure

`reports/device/20261112-device-continue/baseline-logcat.txt` records Enforcing
`system_suspend` read denials at 09:20:16 UTC (lines 4358–4439). The files inherit
`sysfs` or, for FPC, `sysfs_fingerprint_sheng`. The service later explicitly
reports `Permission denied` while reading these same wakeup statistics at
09:50:00 UTC (lines 22372–22438). This is an existing-file label problem, not
evidence of missing kernel files or a failed fingerprint HAL.

The 50 explicit read errors cover ten statistic files per wakeup instance:
`name`, `active_count`, `last_change_ms`, `max_time_ms`, `total_time_ms`,
`active_time_ms`, `event_count`, `expire_count`, `prevent_suspend_time_ms`, and
`wakeup_count`.

| Observed `/sys` path, without the `/sys` prefix | Baseline instance(s) | Explicit read errors |
| --- | --- | --- |
| `/devices/platform/soc/soc:xm_battmngr/wakeup` | `wakeup49` | 10 |
| `/devices/platform/soc/soc:fingerprint_fpc/wakeup` | `wakeup5`, `wakeup6` | 20 |
| `/devices/platform/soc/soc:xiaomi_wifi_gpio/wakeup` | `wakeup17` | 10 |
| `/devices/platform/soc/8c0000.qcom,qupv3_2_geni_se/884000.i2c/i2c-5/5-004c/wakeup` | `wakeup27` | 10 |

The instance numbers are boot-dependent. Their four observed parent `/wakeup`
paths determine the mappings; no device identity is inferred for address 004c.
The kernel capture also retains the associated read denials at 16.329 seconds
and 1800.158 seconds in `baseline-dmesg.txt`.

## Device-tree correction

Add exactly these four parent paths to `sepolicy/vendor/genfs_contexts` with
the existing platform `sysfs_wakeup` type. The FPC wakeup subtree receives the
more specific label while its device control attributes retain
`sysfs_fingerprint_sheng`. Existing goodix, SPI and power-key mappings stay.

The manifest-pinned platform policy already contains
`r_dir_file(system_suspend, sysfs_wakeup)` and
`allow system_suspend sysfs_type:dir search`. Its macro permits reading the
labelled directories, files and symlinks. No new allow rule, type, broad sysfs
permission, ownership change, kernel change or permissive domain is needed.
The service can use its existing policy once these board statistics are
correctly labelled.

## Reviewed references

Reuse the 2026-11-12 refreshed branch revisions recorded by the gesture and
Codec2 investigations, then inspect the exact commits rather than the modified
local reference checkout.

| Repository | Commit | Relevant evidence |
| --- | --- | --- |
| `system/sepolicy` | `d61fd80832f558d52de026097d30d695634e8b0f` | `private/system_suspend.te` already grants `sysfs_wakeup` reading and arbitrary sysfs-directory traversal; `public/te_macros` defines the read macro. |
| `xiaomi-pad-8-pro-development/android_device_xiaomi_piano`, seventeen | `8c0bb4b9d15ea349eaa09d6de0aa4fec43f7ff41` | `sepolicy/vendor/genfs_contexts` labels board-specific `/wakeup` parents and the same `soc:xiaomi_wifi_gpio/wakeup` path as `sysfs_wakeup`. Its different I2C paths are not copied. |
| `LineageOS/android_device_xiaomi_nuwa`, lineage-24.0 | `8e2b6ca4375919035587115189760eed64f14b8d` | The exact repository tree contains no `genfs_contexts`; its device-specific policy does not supply these sheng mappings. |
| `LineageOS/android_device_xiaomi_sm8550-common`, lineage-24.0 | `62f4b9c1d20c88f02e0bc7f1b2c932bd5c750eb1` | `sepolicy/vendor/genfs_contexts` labels goodix, SPI and power-key wakeup paths; it lacks the four observed sheng parents. |

## Validation boundary

r61 passed normal policy compilation and neverallows, actual installed-partition
policy compilation, full AVB and 14 partition/dependency hash checks. Runtime
instances were wakeup49 (battery), wakeup2/3 (FPC), wakeup8 (Wi-Fi GPIO), and
wakeup26 (I2C 004c); the instance numbers remain boot-dependent. All ten files
per instance have `sysfs_wakeup`, while the FPC parent device retains its original
label. The r61 check did not include `wakeup_enable`; r62 adds that exact check
and corrects its label. The real `suspend_control_internal` dump includes all five
names without fresh related read errors or system_suspend AVCs. See
[DEVICE_CONTINUATION_R61.md](DEVICE_CONTINUATION_R61.md) and workspace
`reports/device/20261112-device-continue/r61-runtime/` for exact results.

Source verification passed: all 50 logged read failures resolve beneath
the four added mappings, no duplicate genfs paths are introduced, and FPC
parent-directory lookup selects the existing device label. The sibling control
file was omitted from that original check; the r62 compiled-policy probe checks
`wakeup_enable` and rejects the r61 regression. The scoped
`git diff --check` passed. These are configuration checks only.

Before runtime acceptance, build the normal device policy with its existing
neverallow checks, inspect compiled genfs labels and permissions, package the
reviewed batch, and verify installed partition metadata. On the device, read
back the effective labels for all five wakeup instances, request the suspend
service statistics, and verify it returns those statistics without fresh
permission errors. Confirm Enforcing and the unchanged FPC device labels.
Instance numbers may differ after reboot.

This restores access to wakeup statistics. It does not establish improved
suspend power, a successful physical wake event, or fingerprint authentication
after prolonged standby. Those functional tests remain separate acceptance
items in `DEVICE_TREE_COMPLETION_GOAL.md`.
