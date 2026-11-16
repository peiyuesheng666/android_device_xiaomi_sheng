// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.face;

import android.hardware.keymaster.HardwareAuthToken;
import android.hardware.security.keymint.Algorithm;
import android.hardware.security.keymint.BeginResult;
import android.hardware.security.keymint.Digest;
import android.hardware.security.keymint.HardwareAuthenticatorType;
import android.hardware.security.keymint.IKeyMintDevice;
import android.hardware.security.keymint.KeyCharacteristics;
import android.hardware.security.keymint.KeyCreationResult;
import android.hardware.security.keymint.KeyMintHardwareInfo;
import android.hardware.security.keymint.KeyParameter;
import android.hardware.security.keymint.KeyParameterValue;
import android.hardware.security.keymint.KeyPurpose;
import android.hardware.security.keymint.SecurityLevel;
import android.hardware.security.keymint.Tag;
import android.os.ServiceManager;
import android.security.GateKeeper;
import java.util.Arrays;

/**
 * Verify a genuine Gatekeeper token through an ephemeral auth-bound hardware key.
 * KeyMint checks the HAT MAC and secure timestamp, not a Java comparison of MAC bytes.
 * No PIN, HAT, key blob or crypto output is persisted or logged.
 */
public final class CredentialTokenVerifier {
    private static final int AUTH_TIMEOUT_SECONDS = 120;
    private static final byte[] PROBE = new byte[] {0x53, 0x46, 0x41, 0x43, 0x45};

    public boolean verifyForUser(int androidUser, HardwareAuthToken token) {
        if (androidUser < 0) return false;
        try {
            // Secure ID comes from Gatekeeper's trusted Android-user mapping.
            long sid = GateKeeper.getSecureUserId(androidUser);
            if (!NativeFaceTokens.credentialShape(token, sid)) return false;
            IKeyMintDevice device = IKeyMintDevice.Stub.asInterface(
                    ServiceManager.checkService(IKeyMintDevice.DESCRIPTOR + "/default"));
            return device != null && verifyHardware(device, sid, token);
        } catch (Exception | LinkageError failure) {
            return false;
        }
    }

    static KeyParameter param(int tag, KeyParameterValue value) {
        KeyParameter p = new KeyParameter(); p.tag = tag; p.value = value; return p;
    }

    static KeyParameter[] keyParameters(long sid) {
        return new KeyParameter[] {
            param(Tag.ALGORITHM, KeyParameterValue.algorithm(Algorithm.HMAC)),
            param(Tag.KEY_SIZE, KeyParameterValue.integer(256)),
            param(Tag.PURPOSE, KeyParameterValue.keyPurpose(KeyPurpose.SIGN)),
            param(Tag.DIGEST, KeyParameterValue.digest(Digest.SHA_2_256)),
            param(Tag.MIN_MAC_LENGTH, KeyParameterValue.integer(256)),
            param(Tag.USER_SECURE_ID, KeyParameterValue.longInteger(sid)),
            param(Tag.USER_AUTH_TYPE, KeyParameterValue.hardwareAuthenticatorType(
                    HardwareAuthenticatorType.PASSWORD)),
            param(Tag.AUTH_TIMEOUT, KeyParameterValue.integer(AUTH_TIMEOUT_SECONDS)),
        };
    }

    /** Package-private for camera-free hardware negative tests. */
    static boolean verifyHardware(IKeyMintDevice device, long trustedSid, HardwareAuthToken token)
            throws Exception {
        KeyMintHardwareInfo info = device.getHardwareInfo();
        if (info == null || !hardware(info.securityLevel) || info.timestampTokenRequired
                || !NativeFaceTokens.credentialShape(token, trustedSid)) return false;
        KeyCreationResult key = null;
        BeginResult operation = null;
        byte[] output = null;
        android.hardware.security.keymint.HardwareAuthToken copy = null;
        boolean valid = false;
        boolean cleaned = true;
        try {
            key = device.generateKey(keyParameters(trustedSid), null);
            if (key == null || key.keyBlob == null || key.keyBlob.length == 0
                    || !hardwareAuthEnforced(key.keyCharacteristics, info.securityLevel, trustedSid)) {
                return false;
            }
            copy = NativeFaceTokens.toKeyMint(token);
            operation = device.begin(KeyPurpose.SIGN, key.keyBlob, new KeyParameter[] {
                param(Tag.DIGEST, KeyParameterValue.digest(Digest.SHA_2_256)),
                param(Tag.MAC_LENGTH, KeyParameterValue.integer(256)),
            }, copy);
            if (operation == null || operation.operation == null) return false;
            // Also finish: begin alone is insufficient on implementations that defer checks.
            output = operation.operation.finish(PROBE, null, copy, null, null);
            operation = null;
            valid = output != null && output.length == 32;
        } finally {
            if (operation != null && operation.operation != null) {
                try { operation.operation.abort(); } catch (Exception failure) { cleaned = false; }
            }
            if (key != null && key.keyBlob != null) {
                try { device.deleteKey(key.keyBlob); } catch (Exception failure) { cleaned = false; }
                Arrays.fill(key.keyBlob, (byte) 0);
            }
            if (copy != null) Arrays.fill(copy.mac, (byte) 0);
            if (output != null) Arrays.fill(output, (byte) 0);
        }
        return valid && cleaned;
    }

    private static boolean hardware(int level) {
        return level == SecurityLevel.TRUSTED_ENVIRONMENT || level == SecurityLevel.STRONGBOX;
    }

    static boolean hardwareAuthEnforced(KeyCharacteristics[] groups, int level, long sid) {
        if (groups == null || !hardware(level)) return false;
        boolean secureId = false, password = false, timeout = false;
        for (KeyCharacteristics group : groups) {
            if (group == null || group.securityLevel != level || group.authorizations == null) continue;
            for (KeyParameter p : group.authorizations) {
                if (p == null || p.value == null) continue;
                if (p.tag == Tag.USER_SECURE_ID && p.value.getLongInteger() == sid) secureId = true;
                if (p.tag == Tag.USER_AUTH_TYPE && p.value.getHardwareAuthenticatorType()
                        == HardwareAuthenticatorType.PASSWORD) password = true;
                if (p.tag == Tag.AUTH_TIMEOUT && p.value.getInteger() == AUTH_TIMEOUT_SECONDS) timeout = true;
                if (p.tag == Tag.NO_AUTH_REQUIRED) return false;
            }
        }
        return secureId && password && timeout;
    }
}
