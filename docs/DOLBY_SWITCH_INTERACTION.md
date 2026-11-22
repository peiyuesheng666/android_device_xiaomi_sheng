# Dolby switch interaction repair (r51 installed)

The user redirected cross-app audio investigation to two immediate UI reports:
the Atmos on/off switch could not be clicked and EQ sliders could not be adjusted.
On installed r41 APK version 3.0.1, the view hierarchy reports the master
MonetSwitch enabled and checked but clickable=false. Its constructor sets
focusability but never clickability after replacing the standard button graphic.
The shared component now explicitly enables clicks, covering both the master
switch and dialog-enhancement switch. The installed APK is version 51 / 3.0.2.

The EQ UI was in Dynamic mode, where all five bars are intentionally disabled
and the existing hint says to choose Custom. Selecting Custom enables all five.
An actual touch adjustment reached the native DMS protocol and read back profile
3 parameter 110 at +6/-3/0 dB for the first four native bands; the test returned
them to zero. Thus this report does not justify changing native audio routing
or silently changing the selected sound mode when editing an automatic profile.
The UI remains in Custom for the user's EQ checks.

Evidence: reports/device/20261111-simple/dolby-cross-app-r51/ui-controls-before.xml,
ui-custom-before.xml and native ShengDolby logcat. No screenshot or camera was used.
Normal module build passed. The final mirror verified 32 device-tree inputs;
the fresh public-source audit found all 1243 repositories clean. Packaging
changed only the APK content in system_ext and its vbmeta_system descriptor,
preserved filesystem metadata and verified the complete AVB chain. Those two
images were flashed to ca10ede3 A. All six current partition hashes and all
declared files match; SELinux remains Enforcing and original SystemUI is intact.
The precise old Dolby parse-cache entry was backed up and moved before scanning;
no application data was cleared. Runtime evidence is r51-runtime-readback.json.

The user confirms all three interactions work: master on/off, dialog enhancement,
and EQ after choosing Custom. Native logs contain verified changes across all
five EQ groups and dialog parameter 105. One parameter-110 readback mismatch
occurred during rapid concurrent page operations/reset; retain it in
ui-r51-parameter-logcat.txt rather than claiming an entirely error-free stress
test. Subsequent values verified and the user reports normal controls. Early
off/on XML and AudioFlinger snapshots were not synchronized with user input,
so they are not a valid native on/off comparison.

Original OEM Dolby libraries, controls protocol and accepted Voice compensation
are unchanged in this revision. The subsequent r52 Douyin media repair and
post-reboot acceptance are recorded in DOLBY_CROSS_APP_MEDIA.md.
The enabled r50 report property and standard system key both survived this boot
(1755ec7d-1e85-43fe-9e08-1464d6eb0a64), with the report HAL running.
