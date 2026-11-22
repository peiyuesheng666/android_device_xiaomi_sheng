# Normal boot and Recovery module packaging — 2026-11-13

Normal vendor_boot packaging omitted `qrng_dlkm.ko` from its dependency table.
The board selected only `modules.list.recovery` for `BOOT_KERNEL_MODULES`, while
normal first-stage init still requested qrng in `modules.load.first_stage`.
The two input sets differ by this one boot-only module.

The first normal seven-image build completed, and its module CRC and image
hash checks passed. A stricter check of the unpacked, merged ramdisks found
337 module files but only 336 `modules.dep` entries: qrng was missing there.
Its file survived from the November 5 output directory. The Lineage packaging
macro copies selected modules into the existing output but creates a fresh
depmod staging directory, so the stale file hid the missing package input.
A fresh output directory would also lack the requested file itself.

`BOOT_KERNEL_MODULES` now takes the sorted union of the boot and Recovery
dependency sets. This supplies all 337 modules to vendor_boot and depmod.
Normal and Recovery load order remain separately specified: 116 and 334
entries respectively. Recovery still defers block2mtd until storage is ready.
Its standalone module set remains unchanged; the vendor ramdisk must cover
both modes because the bootloader appends it after the Recovery ramdisk.

The source mirror migrates only the known old assignment, brings both boot
input lists into its checked scope, and rejects unknown local assignments.
Seven source reconciliation regressions pass, including preservation of an
unknown assignment and repeated synchronization. The build wrapper also handles
SIGPIPE so an interrupted output pipe runs its compiler-restoration trap; a
temporary-fixture signal test confirmed restoration and a failed-build receipt.

`tools/verify_sheng_boot_chain.py` checks the seven normal image targets and
their successful build/audit receipts. It unpacks the actual boot, vendor_boot,
init_boot and Recovery images, applies their merge order, and checks load lists,
complete depmod entries, packaged symbol providers and Recovery input bytes.
It also reads both DLKM filesystems and validates module import CRCs against
the matching kernel and module providers. Source GKI zram/zsmalloc have identical
ELF payloads between ramdisks and system_dlkm; only system_dlkm carries their
PKCS#7 signatures, which are verified with this kernel's public certificate.
No vermagic, CRC or module payload is rewritten by this checker.

The corrected normal build completed at 18:22 Singapore time; its compilation
phase took 2 min 17 s (71 actions), with 36 matching source inputs and successful
pre/post public-source audits. The successful run is
`modules-20261113-101854-Gnk3V5` under the WSL
`hardware-diagnostics/sheng-pen-settings-20261112` directory.
The unpacked seven-image verification passed: all 419 modules have 25,134
matching import CRCs; each merged ramdisk has 337 complete depmod entries and
17,087 verified symbol providers. Both GKI signatures and all seven image hash
descriptors passed. The source-fixed vendor_boot contains a newly generated
qrng depmod entry; a stale file is no longer required for the build.

Receipts are in workspace `reports/device/20261113-full-product/boot-module-union-validation`.
The corrected images and matching verification metadata are retained at
`E:/XiaomiPad6SProPort6.18-artifacts/normal-boot-chain-union-20261113`.
The earlier broken image set is rejected by the same dependency-table check.

The earlier snapshot in `E:/XiaomiPad6SProPort6.18-artifacts/normal-boot-chain-20261113`
has `not-for-installation.json`; its limited passing receipt does not supersede
the subsequently discovered depmod failure. It was never flashed.

Reference review retained piano seventeen `8c0bb4b9d15ea349eaa09d6de0aa4fec43f7ff41`,
nuwa lineage-24.0 `8e2b6ca4375919035587115189760eed64f14b8d` and sm8550-common
`62f4b9c1d20c88f02e0bc7f1b2c932bd5c750eb1`. Their board organization does not
replace the sheng-specific boot/Recovery lists. The inspected manifest-pinned
packaging and loader sources are vendor/lineage
`7ce6b1b2cf4614fdb76511694d11ae0518574075`, build/make
`90d006387398ae6899145e6531a304500cfa0f70` and system/core
`65d661b1a536701e8b118be4e9728d7b5ca727c9`.

This is the retained 5.15 Android build configuration. Full target-files,
the parent vbmeta chain, current-system compatibility and hardware acceptance
remain separate requirements. No new image was installed; ca10ede3 A retains
Android r64 and separately accepted Recovery r59. The future 6.18 integration
still requires matching finalized kernel/module inputs from the kernel task.
