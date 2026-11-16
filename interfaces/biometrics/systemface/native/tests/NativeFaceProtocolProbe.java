// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.face;

import android.hardware.keymaster.HardwareAuthToken;
import android.hardware.keymaster.HardwareAuthenticatorType;
import android.hardware.keymaster.Timestamp;
import android.hardware.security.keymint.Algorithm;
import android.hardware.security.keymint.BeginResult;
import android.hardware.security.keymint.Digest;
import android.hardware.security.keymint.ErrorCode;
import android.hardware.security.keymint.IKeyMintDevice;
import android.hardware.security.keymint.KeyCreationResult;
import android.hardware.security.keymint.KeyMintHardwareInfo;
import android.hardware.security.keymint.KeyParameter;
import android.hardware.security.keymint.KeyParameterValue;
import android.hardware.security.keymint.KeyPurpose;
import android.hardware.security.keymint.SecurityLevel;
import android.hardware.security.keymint.Tag;
import android.os.Parcel;
import android.os.Process;
import android.os.ServiceManager;
import android.os.ServiceSpecificException;
import android.security.GateKeeper;
import java.util.Arrays;
import java.security.SecureRandom;

/** No camera, no biometric-service registration, no settings or enrollment mutations. */
public final class NativeFaceProtocolProbe {
    private static int checks;
    private static void check(boolean value) {
        checks++; if (!value) throw new AssertionError("Protocol check " + checks);
    }

    public static void main(String[] args) throws Exception {
        if (Process.myUid() == 0) { Process.setGid(1000); Process.setUid(1000); }
        check(Process.myUid() == 1000);
        absentTransport();
        shapeAndConversion();
        if (args.length == 0 || !"--hardware".equals(args[0])) {
            System.out.println("Native transport/shape: " + checks + " checks passed; camera not opened");
            return;
        }
        IKeyMintDevice device = IKeyMintDevice.Stub.asInterface(
                ServiceManager.checkService(IKeyMintDevice.DESCRIPTOR + "/default"));
        check(device != null);
        KeyMintHardwareInfo info = device.getHardwareInfo();
        check(info != null && info.securityLevel == SecurityLevel.TRUSTED_ENVIRONMENT
                && !info.timestampTokenRequired);
        System.out.println("KeyMint hardware reached; trusted_environment=true; secure_clock=true");
        long sid = GateKeeper.getSecureUserId(0);
        check(sid != 0); // Do not print the secure user ID.
        unboundCryptoControl(device);
        HardwareAuthToken invalid = credential(sid);
        invalid.timestamp.milliSeconds = android.os.SystemClock.elapsedRealtime();
        boolean macRejected = false;
        try {
            // The MAC is deliberately all zeros; this is a negative test, never enrollment.
            boolean accepted = CredentialTokenVerifier.verifyHardware(device, sid, invalid);
            check(!accepted);
            System.out.println("Verifier declined before successful hardware authorization;") ;
            System.out.println("MAC rejection not confirmed: hardware-enforcement prerequisite may be absent");
        } catch (ServiceSpecificException rejected) {
            check(rejected.errorCode == ErrorCode.KEY_USER_NOT_AUTHENTICATED);
            macRejected = true;
            System.out.println("Invalid credential with zero MAC rejected by hardware: KEY_USER_NOT_AUTHENTICATED");
        } finally { Arrays.fill(invalid.mac, (byte) 0); }
        check(macRejected);
        System.out.println("Hardware negative tests: " + checks + " checks passed; camera not opened");
        System.out.println("Genuine credential-HAT positive enrollment verification remains required");
    }

    private static void absentTransport() throws Exception {
        HardwareAuthToken empty = NativeFaceTokens.absentAttestation();
        check(empty.challenge == 0 && empty.userId == 0 && empty.authenticatorId == 0
                && empty.authenticatorType == 0 && empty.timestamp.milliSeconds == 0
                && empty.mac.length == 0);
        Parcel parcel = Parcel.obtain();
        try {
            parcel.writeTypedObject(empty, 0); parcel.setDataPosition(0);
            HardwareAuthToken roundtrip = parcel.readTypedObject(HardwareAuthToken.CREATOR);
            check(roundtrip.mac.length == 0 && roundtrip.timestamp.milliSeconds == 0);
            // Exercise the actual pinned framework serializer from services.jar.
            byte[] wire = (byte[]) Class.forName("com.android.server.biometrics.HardwareAuthTokenUtils")
                    .getMethod("toByteArray", HardwareAuthToken.class).invoke(null, roundtrip);
            check(wire.length == 69);
            for (byte b : wire) check(b == 0);
        } finally { parcel.recycle(); }
    }

    private static HardwareAuthToken credential(long sid) {
        HardwareAuthToken token = new HardwareAuthToken();
        token.userId = sid; token.challenge = 123;
        token.authenticatorType = HardwareAuthenticatorType.PASSWORD;
        token.timestamp = new Timestamp(); token.timestamp.milliSeconds = 1;
        token.mac = new byte[32];
        return token;
    }

    private static void shapeAndConversion() {
        HardwareAuthToken token = credential(42);
        check(NativeFaceTokens.credentialShape(token, 42));
        check(!NativeFaceTokens.credentialShape(token, 43));
        check(!NativeFaceTokens.credentialShape(token, 0));
        check(!NativeFaceTokens.credentialShape(null, 42));
        token.mac[0] = 9;
        android.hardware.security.keymint.HardwareAuthToken copy = NativeFaceTokens.toKeyMint(token);
        check(copy.userId == 42 && copy.challenge == 123 && copy.authenticatorType == 1
                && copy.timestamp.milliSeconds == 1 && copy.mac[0] == 9);
        token.mac[0] = 0; check(copy.mac[0] == 9); Arrays.fill(copy.mac, (byte) 0);
        token.authenticatorType = HardwareAuthenticatorType.FINGERPRINT;
        check(!NativeFaceTokens.credentialShape(token, 42));
        token.authenticatorType = HardwareAuthenticatorType.PASSWORD;
        token.timestamp.milliSeconds = 0; check(!NativeFaceTokens.credentialShape(token, 42));
        token.timestamp.milliSeconds = 1;
        token.mac = new byte[31]; check(!NativeFaceTokens.credentialShape(token, 42));
        token.mac = new byte[0]; check(!NativeFaceTokens.credentialShape(token, 42));
        token.mac = null; check(!NativeFaceTokens.credentialShape(token, 42));
        token.timestamp = null; check(!NativeFaceTokens.credentialShape(token, 42));
    }

    private static void unboundCryptoControl(IKeyMintDevice device) throws Exception {
        KeyCreationResult key = null;
        BeginResult op = null;
        byte[] output = null;
        try {
            key = device.generateKey(new KeyParameter[] {
                CredentialTokenVerifier.param(Tag.ALGORITHM, KeyParameterValue.algorithm(Algorithm.HMAC)),
                CredentialTokenVerifier.param(Tag.KEY_SIZE, KeyParameterValue.integer(256)),
                CredentialTokenVerifier.param(Tag.PURPOSE, KeyParameterValue.keyPurpose(KeyPurpose.SIGN)),
                CredentialTokenVerifier.param(Tag.DIGEST, KeyParameterValue.digest(Digest.SHA_2_256)),
                CredentialTokenVerifier.param(Tag.MIN_MAC_LENGTH, KeyParameterValue.integer(256)),
                CredentialTokenVerifier.param(Tag.NO_AUTH_REQUIRED, KeyParameterValue.boolValue(true)),
            }, null);
            op = device.begin(KeyPurpose.SIGN, key.keyBlob, new KeyParameter[] {
                CredentialTokenVerifier.param(Tag.DIGEST, KeyParameterValue.digest(Digest.SHA_2_256)),
                CredentialTokenVerifier.param(Tag.MAC_LENGTH, KeyParameterValue.integer(256)),
            }, null);
            output = op.operation.finish(new byte[] {1, 2, 3}, null, null, null, null);
            op = null; check(output != null && output.length == 32);
            System.out.println("Ephemeral unbound HMAC control passed; key deleted after test");
        } finally {
            if (op != null && op.operation != null) op.operation.abort();
            if (key != null && key.keyBlob != null) {
                device.deleteKey(key.keyBlob); Arrays.fill(key.keyBlob, (byte) 0);
            }
            if (output != null) Arrays.fill(output, (byte) 0);
        }
    }
}
