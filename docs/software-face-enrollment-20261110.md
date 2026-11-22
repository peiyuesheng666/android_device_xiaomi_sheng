# Software face enrollment guidance 0.3.2

The user confirmed that 0.3.1 mirroring and green-box tracking work. During
comparison, modest changes in distance produced cosine values around 0.5–0.6;
the user considered this usable and requested guidance to move closer during
enrollment. These are reported similarity measurements, not success rates or
an accuracy/liveness evaluation. This batch keeps the comparison algorithm,
model weights, encryption format and previously enrolled samples unchanged.

## Behavior

Enrollment now prompts the user to approach the front camera and keep the
whole face visible. Before feature extraction, both face-box dimensions must
reach 30% of the upright image's short edge, in addition to the existing
single-face, complete-bounds and detector-size checks. This dimensionless
candidate uses the same relative requirement in landscape and portrait.
Distant faces remain visible in the preview but do not advance collection.
Brightness, contrast and sharpness checks still run before admitting features.
Comparison retains the old detector-size floor and displays raw mean cosine
similarity without an acceptance threshold. The user subsequently confirmed
that the new enrollment flow works; no physical camera-to-face distance is inferred.

Pressing enrollment launches the platform credential confirmation. On success,
the resumed activity continues that user-requested camera/enrollment operation
when the preview surface and camera session are ready. The app does not handle
the password. Authorization lasts at most 30 seconds and can be consumed once.
Cancelled/unsolicited results, normal pauses, stop, deletion, comparison and
activity recreation cannot resume an authorized collection. Camera permission
is requested before starting credential confirmation if not already granted.

Stopping the camera and deleting samples repeat collector cancellation on the
camera worker. This closes the race where a start already executing could
recreate collection after the UI thread had cancelled it. Existing epoch,
purpose and sample-generation guards reject results from cancelled operations.
Collection still needs twelve samples spaced at least 250 ms apart and times
out after 30 seconds. No background camera, image persistence, registered
biometric or system unlock was added.

## Validation and scope

References were freshly fetched and remain piano seventeen
`8c0bb4b9d15ea349eaa09d6de0aa4fec43f7ff41`, nuwa lineage-24.0
`8e2b6ca4375919035587115189760eed64f14b8d`, and sm8550-common
`63da741c41384a23416159f148f7ef7c85c8ea61`. The existing face-specific reviews
remain applicable: these references supply no sheng software enrollment
distance fix. The framing/request code is authored here. Before building,
fresh exact-revision fetches and physical-byte checks passed for 21 known
public repositories, all 1,243 project statuses and SDK/R8/JDK toolchains.
Public checkouts and original SystemUI were not patched.

The final scoped APK build passed 234 synthetic checks: 52 core, 37 enrollment,
10 embedding/collector and 135 pipeline cases. Enrollment cases cover framing
boundaries in both orientations and resolutions, duplicate credential requests,
unsolicited/replayed results, expiration, cancellation and one-time use.
Java/D8 compilation, signing, dependency/license inventory and 16 KiB ZIP
alignment passed. This is a scoped development build, not a normal Soong or
complete product build. Formal FaceUnlock integration and API 1 compatibility
remain separate unfinished work.

Final APK SHA256:
`2c8ff688b2413772c684ff0adddec270b88a1e84ca990a7fe7f5f1e93d6546e7`.
VersionCode 5 / versionName 0.3.2 was installed on LineageOS tablet ca10ede3 with
the original development certificate, preserving application data. The installed
APK hash matches the final artifact. No device reboot or partition flash was
performed; the HyperOS tablet was not operated on. The initially installed
0.3.2 candidate was replaced after the cancellation race was found; its earlier
hash and self-test are not the final validation evidence.

Final process PID 7153 passed the native engine/model self-test with generated
blank matrices and no active camera clients. Warm 1280x960 measurements averaged
detection 80.60 ms, total blank analysis 91.14 ms and separate blank feature
extraction 77.38 ms. They do not measure recognition accuracy, actual preview
FPS or real-face feature processing. The tablet clock differs from the host;
the version, PID and APK hash identify the tested final candidate.

Final artifact is `artifacts/ShengFaceLab-enrollment-20261110/ShengFaceLab.apk`.
Disposable build, source verification/sync and installed runtime evidence live
in `reports/device/20261110-resume/face-enrollment/`. The updated sources are
synced to the WSL device tree for future builds. The user subsequently confirmed
the new enrollment flow with “可以了” and proposed cosine >0.5 as a practical
recognition threshold. Record this as user acceptance of the test flow; the
installed lab still makes no unlock decision. Threshold evaluation and formal
system integration are now the first task in REPAIR_GOAL.md.
