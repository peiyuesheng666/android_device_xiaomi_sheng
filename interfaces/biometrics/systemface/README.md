# FaceUnlock

Source-owned software face convenience unlock for sheng. Settings exposes the
only public activity entry. Original SystemUI, public framework sources, hardware
authentication tokens and hardware face sensor declarations are not replaced.

The modern product module targets API 30 and newer, uses the platform certificate
and system UID for the platform-supported lock-screen camera path, and packages
the pinned OpenCV runtime and YuNet/SFace models. `prepare_sheng_face_engine.py`
validates the reviewed dependencies and stages their complete license notices.
`ShengFaceUnlockLegacy` is a separately built API 1 compatibility artifact: it
provides a disabled-feature Settings entry without camera, native libraries,
trust service, shared UID or privileged permissions. It is not installed on sheng.
The modern entry and service also check for actual renewable-trust platform
capabilities; a framework missing that mechanism disables the feature. Internal
SYSTEM_CAMERA devices are excluded from enrollment and lock-screen capture.
Its entry source is compiled against the actual API 1 SDK; old-device runtime
testing was waived by the user and remains unclaimed.

Enrollment, enabling and deletion require platform credential confirmation.
Formal templates use a distinct AES-GCM key and private credential-encrypted
no-backup storage; no photographs, video or frame data are saved. Templates from
the development FaceLab app are deliberately not migrated. Recognition is bounded
to 5 seconds and requires three frames at least 100 ms apart with mean cosine
similarity strictly greater than 0.5. The user selected that candidate boundary;
identity separation, distance, lighting and presentation attacks still require
real user validation. This is a convenience trust agent, not a strong biometric.

Android renewable trust is armed while the user is already credential-unlocked.
The framework downgrades this to TRUSTABLE when keyguard appears. Do not revoke
trust merely on screen off: doing so would prevent a later face result from
renewing trust on the locked device. Only a current qualifying attempt can renew
trust. Keyguard dismissal flags are used only when the system explicitly requests
dismissal. First unlock after reboot, platform strong-auth restrictions, lockdown,
policy restrictions and camera privacy remain enforced. Five actual unsuccessful
comparisons require a successful credential callback to reset the app's lockout.
Trust expiry also requires credentials rather than silently rearming in a loop.

Enabling explicitly saves and enables the system active-unlock wake/intent
settings and dismissal requests for power-button, gesture, wake-key and tap
events. Existing dismissal reasons are retained. Screen-on cannot downgrade a
pending system dismissal request. Disabling restores the saved settings if they
still have the value this app wrote. Unrelated trust agents are retained. Diagnostics expose state
and policy only, never stored features, per-person scores or captured images.

The `retired/` payloads intentionally replace residual legacy face init services,
VINTF entries and the hardware feature XML. Both fresh builds and scoped r42 image
updates therefore withdraw the failed hardware enrollment path. Existing camera
libraries and photographic face-detection models are separate dependencies and
are retained.
The old native modules are disabled, so their init/VINTF install rules cannot
collide with the formally assembled empty retirement fragments.

Normal validation:

```
bash device/xiaomi/sheng/tools/build_hardware.sh ShengFaceUnlock ShengFaceUnlockLegacy \
  sheng-face-retired-fragment sheng-miface-retired-fragment \
  out/target/product/sheng/odm/etc/init/android.hardware.biometrics.face-aidl-service.rc \
  out/target/product/sheng/odm/etc/init/vendor.xiaomi.hardware.miface@1.0-service.rc \
  out/target/product/sheng/vendor/etc/permissions/android.hardware.biometrics.face.xml
```

Use `review_sheng_face_unlock.py` for final installed-output, signature, native
payload, API 1 and synthetic decision checks. A complete product build, installed
runtime checks and human lock-screen trials are separate acceptance conditions.
Agents must not open a camera or collect personal images; human trials remain
user-operated.
