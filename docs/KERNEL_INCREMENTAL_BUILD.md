# Normal full-product incremental build fixes

The 2026-11-13 normal full build passed the corrected touch ELF installation
guard, then stopped because its nested kernel Image was older than `.config`.
The kernel recipe had completed module staging and checked 419 effective
modules; the Image bytes remained unchanged. Kconfig and module packaging
inputs can change without changing the nested kernel's Image output.

The device root `Android.mk` adds `.KATI_RESTAT` for this Image target when
building sheng. The generated normal Ninja rule has `restat = 1`. The kernel
recipe still runs and validates its inputs; command errors remain errors.
This changes no public build rules, kernel sources, configuration or ELF bytes.
The selective preparation step preserves existing root Make declarations and
has passed an idempotence check. The full build subsequently passed at 22:49,
followed by complete package validation at 23:14; see
[FULL_PRODUCT_VALIDATION_20261113.md](FULL_PRODUCT_VALIDATION_20261113.md).

A subsequent incremental run stopped earlier at Lineage's build-manifest XML
recipe. Repo tried to refresh `/root/.repo_.gitconfig.json`, whose timestamp
was older than the global Git config. Ninja's read-only sandbox correctly
rejected this generated cache write. The dedicated wrapper now runs the normal
`repo manifest -r` command before entering Ninja, placing its manifest and log
in the build-evidence directory and warming Repo's Git JSON caches. Global Git
configuration, public sources and sandbox restrictions remain unchanged.

Evidence directories under workspace `reports/device/20261113-full-product`:

- `full-product-touch-elf-run`: original unchanged-Image failure.
- `kernel-restat-preparation`: selective preparation checks.
- `full-product-kernel-restat-run`: generated restat rule and Repo-cache failure.
- `full-product-manifest-cache-run`: successful supervised incremental continuation.

Compilation, package verification and artifact retention have successful
terminal receipts under `full-product-native-validation` and the E-drive
`normal-full-product` snapshot. None of these fixes is a hardware acceptance
or completion of the whole device tree.
