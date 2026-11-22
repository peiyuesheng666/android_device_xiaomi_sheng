# sheng first-stage fs_mgr source variant

This static library inherits the upstream `libfs_mgr_defaults`, retains its
filegroup providers and dependencies, and supplies pinned local copies of the
direct C++ files and headers. Public repositories are not edited.

Only `fs_mgr_overlayfs_mount.cpp` differs from upstream: preserve actual file
and directory child mounts with type-correct placeholders, accept only the
specific legitimate pre-policy missing-context errors, and roll back instead
of covering a child whose preservation failed. No context is fabricated and
kernel mount permission checks remain active. The matching kernel source-root
mountpoint fix is also required for deleted-source binds.

The global include directory preserves upstream private sibling imports such
as `libfstab/fstab_priv.h`; local copied headers remain first. Input identities
and the reviewed patch are pinned by the source-variant lock, and checked by
the first-stage variant's Make gate. Do not treat a declared override, isolated
archive/link, or debug product selection as installed-image or runtime proof.
