# First-setup refresh defaults, 2026-11-11

The user resumed device-tree repairs, deferred FaceUnlock and retained the rule
that implementation stays under device/xiaomi/sheng. The next batch addresses
first-setup refresh defaults and build-input drift. Face r46 remains uninstalled.

The existing receiver only initializes absent settings. A new user can already
have minimum and peak values of 60 Hz, so the new receiver seeds both to 144 Hz
once while user_setup_complete is zero. A per-user, device-protected marker
prevents the second boot broadcast from overwriting a choice. An already set-up
user upgrading from the old receiver keeps existing settings even without the
new marker. Missing rows still receive the supported-panel default. Both writes
must succeed before the marker is committed. The receiver first verifies sheng
and that the default display advertises 144 Hz.

Current read-only evidence on ca10ede3 A: Android is boot-completed and Enforcing;
the owner's min/peak are 144.0, but both installed framework resource defaults
resolve to 60, as does DisplayModeDirector's default configuration. The installed
FrameworkResOverlaySheng APK SHA256 is
9a74d531099e00b8827a25678a3fad53259de8ce73b69a12d0e35b25b273179b.
The Windows source has 144 in both resources; the WSL build copy has 60. r39's
earlier readback resolved both to 144. This is source/build/installation drift;
the writer of the originally reported first-boot setting rows is not established.

Fresh upstream references: piano seventeen
8c0bb4b9d15ea349eaa09d6de0aa4fec43f7ff41 uses 144/144 framework defaults;
nuwa lineage-24.0 8e2b6ca4375919035587115189760eed64f14b8d and its common tree
62f4b9c1d20c88f02e0bc7f1b2c932bd5c750eb1 use default=0/peak=120.
Their panel values are not transplanted. The pinned framework SettingsObserver
uses DisplayDeviceConfig defaults with framework resources as fallback.
SettingsProvider's version-222 migration replaces a saved panel maximum with
Infinity for portability; it does not seed a 60 Hz first-setup pair.

Build, packaging and runtime validation are pending. Existing-owner preservation
and a disposable user's 60/60 initialization must be checked separately. A
disposable user is a scoped initialization test, not a factory-reset acceptance
of the owner's complete SetupWizard path.

r48 was installed on ca10ede3 A with the other functional repairs. All six
partition hashes and declared payload files match the sealed batch; the
installed framework defaults resolve to 144/144 and the owner's existing
144/144 values remain. The installed version-2 receiver passed the disposable
background-user test: seed pre-existing 60/60 during incomplete setup; preserve
a later 60/90 choice across boot broadcasts and user restarts; preserve a
completed user's 60/90 with no marker; fill an absent minimum without replacing
the explicit peak. The temporary user was removed and owner/foreground values
were unchanged. The complete owner's factory-reset SetupWizard path remains
outside this scoped test.
