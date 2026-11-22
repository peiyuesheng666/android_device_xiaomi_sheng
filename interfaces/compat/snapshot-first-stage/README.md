# sheng first-stage snapshot dependency variant

This variant uses the unchanged upstream `libsnapshot_sources` filegroup,
`libsnapshot_defaults`, flags and non-fs_mgr dependencies. Its exported headers
are pinned copies so inherited relative include paths remain valid.

The only dependency change is `libfs_mgr` to `libsheng_fs_mgr_first_stage`.
Without this variant, replacing init's direct fs_mgr dependency would leave
the original one reachable through libsnapshot_init. Do not use link ordering,
duplicate symbol suppression or forced whole-archive inclusion as a substitute
for fixing that dependency graph. Source identity checks include the upstream
snapshot Blueprint, direct providers and headers. Full regenerated Soong graph
and installed-product qualification remain necessary.
