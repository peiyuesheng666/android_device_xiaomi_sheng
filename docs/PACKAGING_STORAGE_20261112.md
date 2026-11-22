# Packaging storage cleanup, 2026-11-12

At the user's request, packaging returned to the C-drive WSL/SSD filesystem.
The E drive is mechanical storage and remains the final artifact location.
The successful r61 work directory is
`/root/sheng-lineage/hardware-diagnostics/device-continue-r61-package-20261112-utf8`.

Removed 71 reconstructable extraction directories from old r47, r48, r50 and
r53 packaging attempts, releasing approximately 45.94 GiB inside WSL. Only
the explicitly selected `*-tree`, `*-readback`, extracted before/after and
baseline directories were selected. Resolved paths and mount boundaries were
checked before deletion, along with active process handles. Fourteen baseline
images were protected by resolved path and pre/post size, inode and mtime
checks. Final partition images, AVB chains, source backups and logs were kept.
The subsequent r61 package/preflight verified the image hashes again.

Also removed the failed first C-drive r61 extraction (2.47 GiB), after keeping
its diagnostic JSON. It contained no partition image or complete-chain output.
Total reusable space recovered inside WSL is approximately **48.4 GiB**.
The VHDX is not a Windows sparse file; this figure describes freed Linux blocks,
rather than a 48.4 GiB reduction in the host VHDX file size. C had approximately
18.5 GiB free after r61 installation and validation. Linux discard was requested
with `fstrim`; no source or compilation cache was removed.

The abandoned E-drive extraction failed because the Windows directory could
not preserve a vendor symlink. A new 24 GiB ext4 staging file was then being
initialized on E; initialization was stopped when the user requested SSD
cleanup instead. It was never mounted or used for the successful package.
Automatic approval review blocked deletion of that file and the failed E
extraction, returning only `blocked by policy`. They remain at:

- `E:\XiaomiPad6SProPort6.18-artifacts\local-work\r61-staging.ext4`
- `E:\XiaomiPad6SProPort6.18-artifacts\device-continue-r61-work-20261112`

Raw receipts are in workspace `reports/device/20261112-device-continue/`:
`staging-cleanup-plan.json`, `staging-cleanup-result.json`,
`failed-c-staging-cleanup.json` and the preserved locale-failure JSON files.
Use `LANG=C.UTF-8 LC_ALL=C.UTF-8` for packaging commands: Java's APK verifier
otherwise rejects the Unicode workspace directory under the default C locale.
