# Touch runtime normal product installer — 2026-11-13

The full target-files build stopped at its normal non-ELF copy check:
`configs/touch/sheng-touch-report` was an ELF executable registered through
`PRODUCT_COPY_FILES`. The previous pen and seven-image builds did not exercise
that vendor executable installer. This is a product integration failure.

The device root Blueprint now declares `sheng-touch-report` as a 64-bit vendor
`cc_prebuilt_binary`, with the actual touchsensor, TensorFlow Lite touch, log
and dl dependencies. The product selects that module and removes the old
copy-file entry. Stripping is disabled so the accepted executable remains
SHA-256 `22a3662e8e9f834a3c96895d795d0cfbb64f18087a14930fd2de0c17b888ffe4`.
Its vendor path, init service and policy are unchanged. The Make ELF guard
remains enabled; no public source or OEM binary bytes are modified.

The selective source preparer migrates only the known copy entry, appends the
new module while preserving other root declarations and product lines, and
checks this Blueprint and ELF in the normal build source-mirror scope.
Temporary ROM reconciliation checks preserve an unrelated product line and
module, preserve the ELF bytes, and confirm that a second preparation changes
no file content. These are source reconciliation checks, not compilation or
hardware qualification. Evidence is under workspace
`reports/device/20261113-full-product/touch-elf-mirror-check`.

The reviewed fresh reference tips are piano seventeen
`8c0bb4b9d15ea349eaa09d6de0aa4fec43f7ff41`, nuwa lineage-24.0
`8e2b6ca4375919035587115189760eed64f14b8d` and sm8550-common
`acec5e2cc86d350a498d2f5b621d6e68699c494c`. Their product/blob organization
supports module installation rather than copying another device's board
values or firmware. The relevant normal ELF guard is in manifest-pinned
build/make `90d006387398ae6899145e6531a304500cfa0f70`,
`core/definitions.mk`'s `copy-non-elf-file-checked`.

The failed run is `modules-20261113-133452-bWtKjT`; its terminal status remains
unsuccessful. The corrected eight-job full run is under workspace
`reports/device/20261113-full-product/full-product-touch-elf-run`.
Later restat and Repo cache failures were corrected in the device-owned rules.
Normal full-product compilation and validation passed; the actual packaged
`VENDOR/bin/sheng-touch-report` is an ELF with the same SHA-256 listed above.
The independent provenance report is workspace `package-image-provenance.json`
under `reports/device/20261113-full-product`, and the terminal package receipt
is `full-product-native-validation/verification.json`. No new image has been flashed.
