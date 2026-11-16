// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.face;

import android.hardware.keymaster.HardwareAuthToken;
import android.hardware.keymaster.HardwareAuthenticatorType;
import android.hardware.keymaster.Timestamp;

/** Transport only. This class cannot create a signed biometric or credential token. */
public final class NativeFaceTokens {
    private NativeFaceTokens() {}

    /**
     * The frozen C++ callback takes a mandatory HardwareAuthToken const reference,
     * not an optional token.
     * The pinned AOSP implementation sends {} for absent, non-STRONG attestation.
     * Keymaster defines empty MAC as an empty token. Use exactly that transport
     * representation; the timestamp object is required by the pinned Java serializer.
     * All secure IDs, challenge and authenticator type remain zero. Never pass the
     * incoming enrollment credential token to an authentication callback.
     */
    public static HardwareAuthToken absentAttestation() {
        HardwareAuthToken empty = new HardwareAuthToken();
        empty.timestamp = new Timestamp();
        empty.mac = new byte[0];
        return empty;
    }

    /** Copy across the distinct keymaster and KeyMint AIDL token types. */
    public static android.hardware.security.keymint.HardwareAuthToken toKeyMint(
            HardwareAuthToken source) {
        if (source == null || source.timestamp == null || source.mac == null) {
            throw new IllegalArgumentException("Missing credential token fields");
        }
        android.hardware.security.keymint.HardwareAuthToken target =
                new android.hardware.security.keymint.HardwareAuthToken();
        target.challenge = source.challenge;
        target.userId = source.userId;
        target.authenticatorId = source.authenticatorId;
        target.authenticatorType = source.authenticatorType;
        target.timestamp = new android.hardware.security.secureclock.Timestamp();
        target.timestamp.milliSeconds = source.timestamp.milliSeconds;
        target.mac = source.mac.clone();
        return target;
    }

    /** Structural checks only. KeyMint verification is still mandatory. */
    public static boolean credentialShape(HardwareAuthToken token, long trustedSid) {
        return trustedSid != 0 && token != null && token.userId == trustedSid
                && token.authenticatorType == HardwareAuthenticatorType.PASSWORD
                && token.timestamp != null && token.timestamp.milliSeconds > 0
                && token.mac != null && token.mac.length == 32;
    }
}
