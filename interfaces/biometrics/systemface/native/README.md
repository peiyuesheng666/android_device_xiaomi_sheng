# Native FaceUnlock protocol

This is a source-owned Android Face V5 provider/session, not a TrustAgent or a
Settings entry. It is currently a **non-product candidate**: registration,
real capture, persistent per-user storage and genuine credential-HAT positive
validation must be completed before product enablement. The interfaces for a
real capture driver and a repository are explicit; test-only implementations
are never installed as a Face service.

`ShengNativeFaceProtocol` and `ShengNativeFaceProtocolProbe` build through normal
Soong. Neither is in `PRODUCT_PACKAGES`. The probe can run through app_process
with the original services.jar in its classpath. It does not register a service,
open cameras, take images, enroll faces, modify Settings or grant trust.

The provider reports one CONVENIENCE sensor, sensor 1 (fingerprint uses 0), a
single enrollment and HAL-owned native preview. It does not support public
application crypto authentication or detectInteraction. Nonzero crypto operation
IDs are rejected. All non-strong authenticator IDs are zero.

Incoming enrollment requires an outstanding random per-user challenge and a
credential token verified by hardware KeyMint. The SID comes from Gatekeeper's
Android-user mapping. An ephemeral hardware-auth-bound HMAC key checks the HAT
MAC and secure freshness; hardware-enforced SID, PASSWORD type and 120-second
timeout are mandatory. Devices requiring a separate secure timestamp token are
currently rejected. Successful enrollment consumes the challenge. None of the
incoming credential token is reused for outgoing recognition callbacks.

The Face AIDL prose requires null non-strong attestation, but its frozen NDK
callback accepts a non-optional token via const reference. The pinned AOSP C++ implementation
uses `{}`; Keymaster documents empty MAC as an empty token. This provider uses
that empty transport representation with zero fields, a zero timestamp and empty
MAC. The pinned Java framework cannot serialize literal null. The camera-free
probe checks Parcel round-trip and the original framework's serializer. This
does not make a signed/valid authentication token, or establish CDD accuracy.

The synthetic session probe checks cancellation, stale callbacks, exact 0.5
rejection, three-frame success, one terminal result, zero authenticator ID,
failure-state retention through session replacement and refusal to clear lockout
with an invalid token. Its repository and capture are test-only. They are not
evidence of persistent-storage, enrollment or real identity accuracy.

Native enrollment requires a real Surface from enrollWithOptions. Legacy
NativeHandle enrollment fails explicitly. Attention/debug features are not
implemented and are rejected; diverse-pose collection and its actual guidance
must be completed with the real capture driver before product enablement. Native
Settings's attention capability resource must accurately describe the engine.

Remaining: production repository, actual camera/engine driver, policy/privacy
callbacks and native preview transforms; finish feature semantics and negative
tests; service startup/VINTF/SELinux, normal builds, package/AVB validation and
announced installation. Then a human performs credential confirmation, native
enrollment and Keyguard tests. r42 remains installed until that candidate is ready.
