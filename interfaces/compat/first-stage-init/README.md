# sheng first-stage init source variant

This debug-only variant retains upstream `init_first_stage_defaults`, the
`init` ramdisk filename, original init sources, and all dependencies except
`libfs_mgr`, which is replaced by `libsheng_fs_mgr_first_stage`, and snapshot's
dependency edge: `libsheng_snapshot_init` retains the upstream snapshot code
but also depends on the repaired fs_mgr. Otherwise `libsnapshot_init` would
reintroduce the original library transitively. The compiler module is not
installed directly: Soong reserves direct `cc_binary.install_in_root` for
upstream's named init modules. `sheng_init_first_stage_ramdisk` uses the
supported `prebuilt_root` installer, with `src: ":sheng_init_first_stage"`,
`ramdisk: true`, filename `init`, and the original init override. Its input is
the same build's compiled executable, never a checked-in binary. No neverallow
exception is added and no public build rule is changed. The installer and
executable permissions must still be checked against actual build output;
source declarations alone do not prove that there is exactly one installer.

The C++ files, headers and NOTICE are pinned upstream copies. Their identities,
upstream defaults and the one fs_mgr delta are locked by
`diagnostics/magisk-overlay-rootfix/source-variants-lock.json`. Use
`materialize_source_variants.py` to prepare or verify both source variants.
Do not regenerate the lock to silently accept an upstream change.

`Android.mk` checks the source identities for selected sheng debug builds and
stops Make on upstream drift, modified copies or a changed repair patch. User
build selection remains unchanged. No public source is patched. Full Soong,
installation, genuine-overlay Android boot and root qualification are required
before deployment; an isolated compile/link is not that qualification.

The real analyzer also rejects direct device-tree dependencies on private
`libcrypto_static`, `libunwindstack_no_dex`, and `libzstd`. Their functions must
not be removed or replaced with a different implementation. Source-owned
`first-stage-crypto`, `first-stage-unwind`, and `first-stage-zstd` variants keep
the original source bytes/defaults (including no-DEX unwinding, Rust demangling
and zstd support). All copied source/header/license inputs and their original
Blueprint/source defaults are pinned in the same lock. Public visibility stays
unchanged. These new library modules still require real graph, compile, link
and runtime qualification; the earlier retained-provider link is not proof.
