# Normal full-product validation

The normal `target-files-package` invocation ended successfully at 22:49 on
2026-11-13, completing 6779/6779 incremental tasks, source checks and the
public-source audit. The complete package validation passed at 23:14. This is
the normal LineageOS 24.0 / 5.15.220 baseline, with no new installation. The successful seven-image
module build remains the separate boot/Recovery result documented in
[BOOT_CHAIN_PRODUCT.md](BOOT_CHAIN_PRODUCT.md).

The current continuation is `full-product-manifest-cache-run` under the same
workspace evidence directory. The touch ELF installer passed; later retries
found unchanged-Image restat and stale Repo Git-cache issues. Device-owned
fixes and their evidence are described in
[KERNEL_INCREMENTAL_BUILD.md](KERNEL_INCREMENTAL_BUILD.md). The wrapper was
only edited after the preceding invocation had ended and its Soong compiler
had been restored. The first receipt in `full-product-touch-elf-validation`
rejected DTBO whole-image equality. That failed receipt remains intact.

The normally packaged DTBO has the exact same 14,726,354-byte payload as the
product DTBO and its `PREBUILT_IMAGES` copy. Releasetools replaces its AVB
footer. Boot, Recovery and vendor_boot payloads also match; init_boot differs
in four empty character-device entry permissions when rebuilt from ROOT.
Filesystem and vbmeta images are normally rebuilt under target-files, as
recorded by the actual successful build log. `PRODUCT_OUT/*.img` cannot be
mixed with the package's vbmeta chain or required to have identical full-file
hashes. Evidence is in workspace `package-image-provenance.json` and
`init-boot-content-comparison/comparison.json` under this full-product run.

`tools/verify_sheng_target_files.py` now provides the postbuild validation step.
It requires terminal success, completed source/public-source audits and the
explicit full target. A seven-image module receipt is rejected before it
creates a validation output directory. It takes the existing output lock and
requires the generated Soong compiler to have been restored before reading
the product images.

The postbuild verifier now audits its host Python tools before trusting their
results. `audit_sheng_releasetools.py` uses the provisioned Soong Python 3.13
runtime to compare both checked source hashes and complete code objects against
fresh compilation of the selected source inputs. Twenty modules across
validate_target_files, check_target_files_vintf, avbtool and the image exporter passed on the current
host. A changed source and a changed bytecode body retaining the original hash
header were both rejected; the test changes existed only in memory.

The source mapping follows the selected Soong libraries. In particular,
ota_metadata_proto compiles ota_metadata.proto, so its embedded generated
Python must not be compared with the checked-in ota_metadata_pb2.py merely
because the names match. Generated proto modules, native tools and the runtime
are outside this Python source audit. Its receipts are under workspace
`reports/device/20261113-full-product/host-tool-source-audit`.

The validator exports the ZIP with normal `img_from_target_files`, then checks
all 14 exported images byte-for-byte against its IMAGES members. An existing
image directory can be reused only after the same full comparison. It records
product-output hashes separately. The boot/module checker takes the coherent
image directory while retaining the build output as the kernel, symbol and
Recovery metadata source. The validator also checks
the A/B and dynamic partition sets, super-group capacity and packaged kernel
metadata. It runs the manifest-pinned normal host tools for target-files,
VINTF and the previously qualified boot/module verifier. VINTF remains
enforced and includes the packaged kernel configuration and version.

The pinned build/make `validate_target_files.py` assigns a root AVB key variable
but does not pass `--key` to its AVB verification command. Our additional
device-owned invocation supplies the expected RSA4096 root key explicitly and
the expected RSA2048 vbmeta_system public key and rollback-index location.
The pinned avbtool propagates a root `--key` to a followed child. An RSA4096
root and RSA2048 child therefore fail that combined CLI invocation even when
the chain is correct. The device verifier validates the root signature and
exact expected child key/location, then the child signature and its descriptors
with the child key. Independent real-package checks passed for both keys and
all image hashes/hashtrees; wrong root/child keys and a wrong chain location
were each rejected. The full run also passed its remaining checks. Evidence is
in `avb-key-rejection-regression.json` and the two `avb-*-explicit-key.log` files.
It checks coverage of the packaged image set. Public
sources are unchanged: build/make is
`90d006387398ae6899145e6531a304500cfa0f70` and external/avb is
`01ecfc9c3df4fbe3e785185742f3313252e70a18`.

The existing root vbmeta configuration uses flags 3. The validator records
the actual flags and software chain verification; it does not claim locked
secure boot. Upstream per-file consistency checks require system/vendor block
maps. This normal ZIP has sparse system and vendor images but no IMAGES block
maps, so no per-file comparisons are claimed. Image hashes/hashtrees are checked
through AVB. Boot, module and Recovery source comparisons have their separate
explicit scope; they do not imply exhaustive file checks for all filesystems.

Releasetools extracts the ZIP and activates APEXes for VINTF. `--tmpdir` must
name an existing directory with Linux symlink and character-device support
and enough space; the validator probes these capabilities first and reserves the
expanded archive size, image workspace and 5 GiB before starting. Keep builds
on the C-drive SSD. If needed, use space within the final artifact directory
on E for scratch rather than migrating the build output. Direct E-drive DrvFS
extraction failed on the relative fingerprint library symlink. The failed
`full-product-split-key-validation` receipt is preserved. The rerun uses a
native WSL Linux directory after reserving 5 GiB of host C space in addition
to the calculated validation requirement. A task-owned ext4 scratch file on
E has also been created and mounted; relative symlinks and character devices
passed its independent probe. It is available for later runs and does not
change product images or the WSL system disk configuration. See
`native-root-scratch-reserve.json` and `native-validation-scratch.json`.

The prepared checker passed Python syntax validation and rejected the genuine
seven-image build receipt. Evidence is under workspace
`reports/device/20261113-full-product/full-validator-preparation`. These are
preparation checks only. The actual terminal receipt is now workspace
`reports/device/20261113-full-product/full-product-native-validation/verification.json`:
14 coherent images, AVB root/child keys, target-files validation, enforced
VINTF, 419 modules and 25,134 import CRCs passed. Normal and Recovery ramdisks
each have 337 complete dependency records and 17,087 provider checks. Packaged
Recovery source/touch hashes and the two GKI module signatures also passed.
No IMAGES block maps exist, so the receipt explicitly claims no per-file
comparison through the upstream sparse-image validator.

On a successful full run, `verification.json` records
`full_product_build_passed:true`. Hardware acceptance, new kernel integration
and completion of the entire device tree remain explicitly false and require
their own evidence. The running build wrapper's historical
`full_product_build_passed:false` field does not substitute for this actual
package result.
