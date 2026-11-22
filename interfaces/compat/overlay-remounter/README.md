# sheng overlay remounter

## Current baseline: Native05 (2026-11-21)

Native05 supersedes the earlier bare-system checkpoints below. Two independent
Magisk boots and one KernelSU LKM boot passed genuine `/system` overlay,
`init_exec`, root, Enforcing, roughly 90 seconds of observation, and Recovery
round trips with the 2 MiB rawdump region preserved. This is debug-product
coverage; it is not user-build or full hardware qualification.

The active `_b` KSU boot exposes `/system/xbin/overlay_remounter` at SHA-256
`2a0df4e9b4846b0045caa674319ae89c7b4b864bfd530b25c14741764554544d`
and `/system/bin/init` as `u:object_r:init_exec:s0`. The runtime file was read
back; it was not reproduced from the current checkout in this check. The
Magisk and KSU boot pairs are pinned in
`reports/sheng-magisk-real-overlay-20261121a/native05-c-only-boot-pairs.json`.
They use the same preserve boot, Recovery and modules; only `init_boot_b` and
its matching `vbmeta_b` differ. The C-only Magisk pair matches the previously
booted images exactly and was not newly flashed. Sections below are historical.

## Current evidence: product stack correction (2026-11-21)

UPDATE: the corrected binary is now installed and read back. Bounded run
`959658ec369b9d29` genuinely recreated `/product`, `/vendor` and `/odm`
overlays in Enforcing, completed Android boot and returned Magisk uid0.
The kernel recorded `TEST_RETURN_BOOTLOADER timeout=45 fault=0` at45.050876s;
preserve boot/root were restored before cold Recovery, all readbacks passed,
and both CRC/footer-valid rawdump slots survived an identical second read.
This was still WITHOUT `/system` overlay, so full acceptance, stable repeated
boots and the matching KSU fallback remain pending. Recovery bootID is
`7d27b8c6-95d8-4f53-b486-126b6112506d`. The preparation checkpoint below is
historical; the no-/system-overlay acceptance constraint still applies.

Run `69ba13d70d766946` captured the exact rejection in Enforcing: ext4
mount36 at `/product`, with overlay45 parent36 at the same path, both private.
The old selector rejected this normal lower/overlay stack before moving any
children. PID1 then exited127. Both rawdump slots passed CRC/footer checks;
the Recovery reread was identical. Preserve boot/root were restored and read
back. That failure checkpoint used the diagnostic system/child and had no
successful Android boot; the scoped correction result is recorded above.

The corrected selector identifies the unique overlay and requires all other
same-path mounts to form its complete linear ancestor chain. Covering mounts,
disconnected aliases, multiple overlays, duplicate IDs, propagation, cycles
and duplicate child points still fail closed. Original inode/label preservation
and real overlay teardown/recreation are unchanged. The old header reproduces
the captured rejection; the corrected header passes the same fixture and
negative cases. A compiled Android test passed all ten private Recovery
namespace syscall cases, including a partition-like stacked lower mount,
with PID1 mountinfo and rawdump unchanged. This is NOT Enforcing runtime
acceptance. The subsequent package/deployment and scoped Enforcing Android
boot result are recorded in the UPDATE above, separately from these tests.

IMPORTANT: this latest capture did NOT mount `/system` overlay. Retained
fastbootd source explicitly tears down the flashed partition's overlay in
`WipeOverlayfsForPartition` before flashing. Therefore a subsequent bare-system
boot must not be counted as real-/system-overlay acceptance: standard overlay
setup must be restored and its actual early-boot mount verified after the
final system flash. The original archived scratch overrides must be retained.
Older "current/latest" headings below describe historical checkpoints only.

## Real-overlay attempt (2026-11-21; current state)

Signed debug flags1 root passed fresh full two-level AVB payload verification,
including a negative corrupted-boot test, and ONLY vbmeta_b was flashed/read
back. Stock disable-verity then provisioned standard system upper/work dirs
after a successful read-only archive/space preflight; original archive hashes
and signed root bytes were preserved. Preparation boot had root/Enforcing.
ONE subsequent real-overlay startup attempt exposed no Android ADB window;
bounded software Recovery return also failed. No kernel/logcat evidence was
captured for this attempt. Remounter/getfilecon failure location and actual
overlay acceptance are still UNKNOWN, not passed. Target currently exposes
neither ADB nor fastboot. Manual bootloader return is needed before immediate
Recovery/pstore capture; do not retry Android or mark a flags0 boot as a repair.
See `reports/sheng-magisk-real-overlay-20261121a/STATUS.md`, `runtime01/`,
`provision02/` and `deploy-debug01/`. Earlier state descriptions are historical.

## Scratch archive preparation (2026-11-21; latest)

The old scratch overlay tree is now atomically archived in the same filesystem
as `overlay.before-rootfix-20261121`. Device checks prove all 20 nodes, five
file hashes, original inodes and every xattr are preserved; no file deletion,
copy or relabel occurred. Parent/PID1 mounts were unchanged. Returned Recovery
b and verified all six direct partition hashes and retained rawdump unchanged.
Installed root remains signed flags0. A signed flags1 debug-overlay candidate
passed flags-only signature/descriptor checks but is NOT flashed or fully
payload-rehashed. Original real-/system-overlay acceptance and KSU fallback
remain pending. See `reports/sheng-magisk-real-overlay-20261121a/STATUS.md`.
The following read-only preflight describes the earlier unarchived state.

## Real-overlay preflight (2026-11-21; latest, acceptance still pending)

Five distinct non-system-overlay Android boots each completed for 90 seconds
with Magisk root/Enforcing. UDC super-speed/device and the internal HWC display
were observed; this is not an MTP stress pass. Removed the two historical
overlay=off flags from canonical/native normal fstab inputs without changing
AVB or other fields; 13 tests and six actual Ninja copy edges passed. No image
was rebuilt or partition flashed for that source/staging alignment.

Read-only norecovery scratch inventory in a recursively-private namespace
proved five old vendor/ODM upper files differ from current effective lower
files. Their content archive is persisted on E:; the original scratch and full
xattrs remain untouched (the tar is not a complete xattr/filesystem backup).
Reconcile these old overrides safely before activation. Actual /system-overlay
handoff/remounter acceptance, repeat boots in that condition and KSU rollback
remain pending. See `reports/sheng-magisk-overlay-acceptance-20261121a/STATUS.md`
and `preflight-qualification.json`. Current device is verified b-slot Recovery.

## Dolby follow-up actual runtime (2026-11-21; overrides historical status)

Only product_b and matching vbmeta_system_b were updated with the complete
source-built Dolby APK v52 (scoped javac/D8 build, not a full Soong product build).
Filesystem delta/security metadata, exact AVB chain and full readback passed.
One completed Android boot remained stable for 90 seconds with Magisk 31.1 root
and global Enforcing. The effective runtime package APK hash/path/version match
the qualified source build. No Dolby creation failure or RescueParty warm reboot
was observed in this bounded run. Actual Recovery roundtrip, final kernel build
ID, 343 module files, boot-family hashes and preserved rawdump were rechecked.

**The actual root was system-verity ext4, not overlay.** Original real-/system-
overlay failure-condition acceptance, repeated boots and new-combination KSU
rollback remain pending. No app/RescueParty/SELinux bypass, wipe, slot switch or
public source edit. Old-version cleanup has not occurred. See
`reports/sheng-dolby-source-repair-20261121a/STATUS.md` and
`completion01/qualification.json`; the original CRLF-sensitive hash check is
retained and corrected read-only from existing evidence, without another boot.

## Deployment override (2026-11-21)

The audited init/remounter and matching policy/system images are now installed
on slot b with all ten candidate partitions hash-read back. A stale-Image bug
in the device module build wrapper was then fixed: Image is regenerated from
the post-module final vmlinux and checked against its split-BTF base before
packaging. Only boot_b/vbmeta_b were updated for that correction. One actual
new Recovery boot now matches final vmlinux build ID and all 343 ramdisk module
files/loaded notes, without the prior BTF warning; rawdump remains unchanged.
See `reports/sheng-magisk-image-consistency-20261121a/` (especially
`recovery01/readonly-completion.json`). Android real-overlay/Enforcing/Magisk
root/reboots and new-combination KSU rollback remain UNVERIFIED. The following
historical not-deployed descriptions do not describe the current partition state.

## Current source integration (2026-11-20)

Both installers now use preferred `cc_prebuilt_binary` adapters named exactly
`overlay_remounter` and `init_first_stage`, consuming this build's source compiler
outputs. The compilers are noninstallable. This replaces the original providers
before generating Make installation/symbol rules instead of merely overriding
their package selection. The experimental remounter Make installer is removed.
Canonical runtime paths, ELF checks, labels and root neverallow rules are retained.

The device product sets `sheng.first_stage_rootfix` only for debug products;
actual Make configuration verifies true on userdebug and false on user. All
inherited Qualcomm namespaces are unchanged. Run product setup with the existing
`CUSTOM_BUILD=sheng` input: omitting it skips BoardConfigLineage/Qcom and produces
an incomplete configuration; adding namespace/visibility exceptions is not a fix.
Focused source tests and real isolated Soong fixtures pass. Fresh integrated
Soong analysis, strict Kati installation rules and actual Ninja compilation
now pass. Both canonical staging files match their source-compiler and preferred
adapter outputs byte-for-byte, with static AArch64 ELF checks passed. The actual
init link response includes all five owned private archives; the source gate
and a strict verbose/explain incremental no-work check also pass. Receipts:
`reports/sheng-magisk-preferred-real-build-20261120a/`,
`reports/sheng-magisk-preferred-install-graph-20261120b/`, and
`reports/sheng-magisk-preferred-artifact-audit-20261120b/`.
This qualifies the two binaries, not a complete product or deployable image.
Matching full kernel/modules, new image/AVB integration and Android Enforcing
Magisk boot/root/Recovery acceptance remain pending.
Historical installer experiments below are superseded, not deployment candidates.

## Evidence (2026-11-20)

One bounded real-device replay, run `43688be29d73ba3c`, captured the failing
`/system` overlay (mount 45) and three direct tmpfs child mounts (67–69):
`init.zygote32.rc`, `init.zygote64.rc`, and `init.rc`. Stock overlay_remounter
attempted ordinary unmount five times, received EBUSY, then PID 1 exited 127.
The kernel's `propagate_mount_busy()` rejects a nonempty child-mount list.
The diagnostic boot was replaced by the prior preserve-rawdump boot before
returning to Recovery. No slot switch, userdata wipe, or system flash occurred.

## Candidate, not a workaround

`mount_preserver.h` parses mount IDs/parent IDs, selects direct child mount
roots (retaining nested subtrees), creates file/directory-correct holders,
and uses MS_MOVE without copying or relabeling original inodes. It checks
mount ID and device/inode identity after staging and restoration. Preparation
and unmount failures restore moved children; cleanup never removes live holders.
Ambiguous stacks (not a verified lower/overlay ancestor chain) and propagated
subtrees fail closed.

`overlay_remounter.cpp` performs a real overlay unmount and recreation in the
normal remounter domain, then restores the original children and execs init.
It does not disable overlay, use lazy unmount, forge existing file labels,
or relax kernel security checks. Recreation failure remains fatal and retains
holders for diagnostics; this is not claimed to be a fully reversible transaction.

## Verified and pending

- Android static binary linked using retained target compile/link flags.
- Same header exercised by an Android static syscall test in an isolated
  Recovery mount namespace: empty overlay, three rc-like file binds, deleted
  sources, directory plus nested bind, rollback, preparation failure, partial
  move failure, restoration retry, and foreign staging-directory protection pass
  (nine cases).
  Parent mountinfo is byte-identical before/after; test files were removed.
- WSL host runs reproduce MS_MOVE ENOENT for deleted sources; that host-kernel
  limitation is recorded as a failed host test, not suppressed or called a pass.
- Device Android.bp overrides the stock remounter through the debug-only
  `product.mk` selection. BoardConfig includes its private system_ext policy.
  These are source declarations, not proof of a regenerated product graph or
  installed image. No product image has been deployed with this remounter.
- The device-owned staging TE passed combined platform/system_ext/product/
  vendor/ODM compilation with neverallow checks enabled and the permissive
  domain set unchanged. Follow-up `policy04` also checks all combined
  file-context entries against that policy, compiles them, and validates five
  exact path lookups against the full database. The actual product graph
  still requires build-system qualification. Existing
  precompiled-policy sidecars must be reconciled before image deployment.
- Enforcing Android runtime, full recreation-failure recovery, and repeated
  boots remain **pending**. Recovery testing is not SELinux acceptance.
- Public fs_mgr/init/remounter sources remain untouched. The kernel candidate
  is now in the actual source kernel package, with an updated source inventory
  and an additive pinned provenance-contract extension. All 2490 original LTS
  source checks remain; an isolated compile with production saved flags passes
  and all 25 object export CRCs match baseline. Full kernel/modules rebuild is
  not claimed. See `reports/sheng-magisk-kernel-source-integration-20261120a/`.
  Source-owned init/fs_mgr variants now retain the upstream defaults while
  replacing only the first-stage fs_mgr dependency and its reviewed mount
  preservation implementation. Their 24 copied C++ files compile and the
  isolated first-stage links; a source-identity Make gate rejects drift. Actual
  debug product dumpvars selects the variant. Full regenerated Soong graph and
  final single-installer override qualification remain pending. See
  `reports/sheng-magisk-source-variants-20261120a/`. The source-variant Soong
  target-closure analysis passed in `reports/sheng-magisk-source-variants-soong-20261120j/`,
  but its real Ninja parse exposed duplicate remounter symbol outputs. Earlier failed/stopped attempts are
  retained under `reports/sheng-magisk-remounter-soong-20261120a/` and `...b/`.

Evidence lives in workspace `reports/sheng-magisk-busytrace-20261120d/`.
Product declarations, physical-backing backups (not snapshot-composed views),
policy/file-context qualification and sidecar derivation are recorded in
`reports/sheng-magisk-remounter-integration-20261120a/`. No partitions were
written in that follow-up. Pro pen is excluded from the active repair scope
by the user's instruction; none of its source is changed by this candidate.

## Offline image trial (not ready to flash)

`image-trial03/qualification.json` records qualified system/system_ext leaf
images and a signed vbmeta_system. Four existing files were replaced, with
payload, UID/GID, modes and exact SELinux xattrs read back. Both hashtrees and
the vbmeta_system signature pass; unrelated vbmeta_system descriptors and its
key/flags/rollback fields are preserved. The generated sidecar hashes the
actual backing image's mapping with the new CIL. Timestamps/allocation and a
whole-filesystem semantic inventory are not compared. This is incremental
image qualification, not a full source/product rebuild.

The installed root vbmeta remains flags=3 and four boot hash descriptors are
stale. Do NOT deploy this set alone or clear the device flags independently.
The device-tree default no longer forces flags=3, as confirmed by actual
product dumpvars. The offline root-chain reconciliation now passes in
`reports/sheng-magisk-captured-avb-chain-20261120b/qualification.json`:
ten freshly captured companions match device hashes; the flags=0 candidate
retains the root key and signed child-chain key, updates four stale boot
descriptors, and verifies both levels' signatures and all hash/hashtree
descriptors with official retained avbtool. Its recursive CLI passes the
root PEM to the different-key child, so the tool verifies levels separately
with explicit PEMs and an exact child-PEM-to-signed-chain-key check. Wrong
keys, a wrong chain key and corrupted payload are rejected in real-avbtool
synthetic tests. No level or data check is omitted. Installed flags remain3;
no flash/reboot/slot switch occurred. This is not a hardware trust, full
Soong/product build or Android runtime pass. Do not flash root alone or relock.
Enforcing Android acceptance is still required. `overlay_remounter` is not permissive in the
compiled candidate; nine other baseline permissive domains remain unchanged.

## Canonical-path installer split (2026-11-20, validation pending)

**This split is NOT deployable.** Actual strict product Kati parsing failed on
duplicate `ramdisk/init` installation producers from the public init module and
the existing owned `prebuilt_root`. The public xbin remounter install producer
also remains. Product-list `overrides` is not sufficient to remove these rules.
See `reports/sheng-magisk-remounter-real-kati-20261120b/` and
`reports/sheng-magisk-fresh-graph-build-20261120c/`.

A real isolated Soong fixture now passes for preferred `cc_prebuilt_binary`
modules consuming freshly source-built compiler outputs, replacing the public
modules across the sheng namespace. It keeps the exact allowed `init_first_stage`
root module name and all default global neverallow rules. User builds retain the
public modules; debug configuration replaces them and suppresses their symbol
outputs. This mechanism has NOT yet been integrated into the product or tested
on Android; see `source_replacement_fixture_test.go` and the fixture reports.

`sheng_overlay_remounter` compiles source with its own unique output stem.
The sheng/debug-only Make executable `sheng_overlay_remounter_install` consumes
its normal Make bridge output, overrides the public installed module, and keeps
`/system/xbin/overlay_remounter`. Soong `overrides` alone did not prevent both
binaries from producing the same symbol output even before installation.
The split does not rename the runtime path, change its label or invocation,
relax duplicate-output errors, or disable ELF checking. No public source changed.

The first split analysis (`reports/sheng-magisk-source-variants-soong-20261120k/`)
passed and removed the duplicate symbol edge, but `installable: false` also hid
the compiler from the Make export. That attempt is not a working installer.
The corrected compiler keeps the normal Make bridge and is NOT selected in
the product or the installer's `LOCAL_REQUIRED_MODULES`; only its built-file
prerequisite is pulled. This must be verified in the real installed-file list
to ensure no second executable is deployed.

Nine source-contract/storage/discovery tests pass. Corrected analysis is under
`reports/sheng-magisk-source-variants-soong-20261120l/`; its terminal result,
duplicate-free Ninja parse, real Make bridge/install selection and actual
current-library compilation must be checked independently. Source-contract tests
are not evidence of those results, and this is not an Android Magisk runtime pass.
