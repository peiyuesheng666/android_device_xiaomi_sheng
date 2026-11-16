// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.face;

import android.hardware.biometrics.face.Feature;
import android.os.UserHandle;
import android.os.UserManager;
import android.security.GateKeeper;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyInfo;
import android.security.keystore.KeyProperties;
import android.system.Os;
import android.util.AtomicFile;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.GCMParameterSpec;
import org.lineageos.sheng.facelab.FaceEmbedding;
import org.lineageos.sheng.facelab.SampleCollector;

/** CE embeddings and authenticated DE identity/lockout metadata; no pictures. */
public final class EncryptedFaceRepository implements FaceRepository {
    private static final int KEY_NAMESPACE = 10001;
    private static final int MAGIC = 0x53464e31, VERSION = 1, LIMIT = 16 * 1024;
    private static final String MODEL = "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79";
    private final int user;
    private final UserManager users;
    private final AtomicFile metadata, template;
    private final String alias;

    public EncryptedFaceRepository(int user, UserManager users) {
        this(user, users, new File("/data/system_de/" + user + "/sheng_face"),
                new File("/data/system_ce/" + user + "/sheng_face"), "sheng_native_face_u" + user + "_v1");
    }
    // Only camera-free storage tests supply alternate, isolated self-test paths.
    EncryptedFaceRepository(int user, UserManager users, File de, File ce, String alias) {
        if (user < 0) throw new IllegalArgumentException("Invalid user");
        this.user = user; this.users = users; this.alias = alias;
        metadata = new AtomicFile(new File(de, "metadata.aesgcm"));
        template = new AtomicFile(new File(ce, "template.aesgcm"));
    }

    private boolean unlocked() { return users.isUserUnlocked(UserHandle.of(user)); }
    private long sid() { return GateKeeper.getSecureUserId(user); }
    private static final class State {
        int id, failures;
        long sid;
        byte[] features = new byte[0];
    }
    private static final class SensitiveBytes extends ByteArrayOutputStream {
        @Override public void close() { Arrays.fill(buf, (byte) 0); reset(); }
    }
    private State state() throws Exception {
        byte[] plain = read(metadata, "metadata");
        State state = new State(); state.sid = sid();
        if (plain == null) return state;
        try (DataInputStream in = new DataInputStream(new ByteArrayInputStream(plain))) {
            if (in.readInt() != VERSION) throw new IOException("Metadata version");
            state.sid = in.readLong(); state.id = in.readInt(); state.failures = in.readInt();
            int features = in.readInt();
            if (state.id < 0 || state.failures < 0 || state.failures > 5 || features < 0 || features > 1) {
                throw new IOException("Metadata range");
            }
            state.features = new byte[features]; in.readFully(state.features);
            if (features == 1 && state.features[0] != Feature.REQUIRE_DIVERSE_POSES) throw new IOException("Unsupported feature");
            if (in.read() != -1) throw new IOException("Trailing metadata");
        } finally { Arrays.fill(plain, (byte) 0); }
        if (state.sid != sid()) {
            // Credential replacement/removal invalidates both old metadata and embeddings.
            deleteKey(); metadata.delete();
            if (unlocked()) template.delete();
            state = new State(); state.sid = sid();
        }
        return state;
    }
    @Override public synchronized int enrollmentId() throws Exception { return state().id; }
    @Override public synchronized int failures() throws Exception { return state().failures; }
    @Override public synchronized byte[] features() throws Exception { return state().features.clone(); }
    @Override public synchronized void failures(int count) throws Exception {
        if (count < 0 || count > 5) throw new IllegalArgumentException("Failure count");
        State state = state(); state.failures = count; writeState(state);
    }
    private void writeState(State state) throws Exception {
        try (SensitiveBytes bytes = new SensitiveBytes(); DataOutputStream out = new DataOutputStream(bytes)) {
            out.writeInt(VERSION); out.writeLong(state.sid); out.writeInt(state.id);
            out.writeInt(state.failures); out.writeInt(state.features.length); out.write(state.features);
            byte[] plain = bytes.toByteArray();
            try { write(metadata, "metadata", plain); } finally { Arrays.fill(plain, (byte) 0); }
        }
    }
    @Override public synchronized float[][] load() throws Exception {
        if (!unlocked()) throw new IllegalStateException("Credential-encrypted user is locked");
        State state = state();
        if (state.id == 0) return null;
        byte[] plain = read(template, "template");
        if (plain == null) throw new IOException("Enrolled template missing");
        float[][] values = null;
        boolean valid = false;
        try (DataInputStream in = new DataInputStream(new ByteArrayInputStream(plain))) {
            if (in.readInt() != VERSION || in.readLong() != state.sid || in.readInt() != state.id
                    || in.readInt() != SampleCollector.REQUIRED) throw new IOException("Template identity");
            values = new float[SampleCollector.REQUIRED][FaceEmbedding.LENGTH];
            for (float[] sample : values) {
                for (int i = 0; i < sample.length; i++) sample[i] = in.readFloat();
                FaceEmbedding.validate(sample);
            }
            if (in.read() != -1) throw new IOException("Trailing template data");
            valid = true; return values;
        } finally {
            Arrays.fill(plain, (byte) 0);
            if (!valid && values != null) for (float[] sample : values) Arrays.fill(sample, 0);
        }
    }
    @Override public synchronized void enroll(int id, float[][] samples, byte[] features) throws Exception {
        if (!unlocked() || id <= 0 || samples == null || samples.length != SampleCollector.REQUIRED
                || features == null || features.length > 1) throw new IllegalArgumentException("Enrollment state");
        if (features.length == 1 && features[0] != Feature.REQUIRE_DIVERSE_POSES) throw new IllegalArgumentException("Features");
        State state = state();
        if (state.id != 0 || state.sid == 0) throw new IllegalStateException("Credential or space unavailable");
        try (SensitiveBytes bytes = new SensitiveBytes(); DataOutputStream out = new DataOutputStream(bytes)) {
            out.writeInt(VERSION); out.writeLong(state.sid); out.writeInt(id); out.writeInt(samples.length);
            for (float[] sample : samples) {
                FaceEmbedding.validate(sample); for (float value : sample) out.writeFloat(value);
            }
            byte[] plain = bytes.toByteArray();
            try {
                write(template, "template", plain);
                state.id = id; state.failures = 0; state.features = features.clone();
                try { writeState(state); } catch (Exception failure) { template.delete(); throw failure; }
            } finally { Arrays.fill(plain, (byte) 0); }
        }
    }
    @Override public synchronized void remove() throws Exception {
        State state;
        try { state = state(); } catch (Exception malformed) {
            state = new State(); state.sid = sid(); state.failures = 5;
        }
        // Cryptographic deletion also works when this user's CE filesystem is locked.
        deleteKey();
        if (unlocked()) template.delete();
        metadata.delete(); state.id = 0; state.features = new byte[0]; writeState(state);
        if (unlocked() && template.getBaseFile().exists()) throw new IOException("Template deletion failed");
    }
    private SecretKey key(boolean create) throws Exception {
        KeyStore store = keyStore();
        if (!store.containsAlias(alias)) {
            if (!create) throw new IOException("Encryption key missing");
            KeyGenerator generator = KeyGenerator.getInstance("AES", "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(alias,
                    KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                    .setNamespace(KEY_NAMESPACE).setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setUnlockedDeviceRequired(false).build());
            generator.generateKey();
        }
        SecretKey key = (SecretKey) store.getKey(alias, null);
        KeyInfo info = (KeyInfo) SecretKeyFactory.getInstance("AES", "AndroidKeyStore")
                .getKeySpec(key, KeyInfo.class);
        if (info.getSecurityLevel() != KeyProperties.SECURITY_LEVEL_TRUSTED_ENVIRONMENT
                && info.getSecurityLevel() != KeyProperties.SECURITY_LEVEL_STRONGBOX) {
            throw new IOException("Hardware encryption key required");
        }
        return key;
    }
    private void deleteKey() throws Exception {
        KeyStore store = keyStore(); store.deleteEntry(alias);
        if (store.containsAlias(alias)) throw new IOException("Key deletion failed");
    }
    private static KeyStore keyStore() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(new android.security.keystore2.AndroidKeyStoreLoadStoreParameter(KEY_NAMESPACE));
        return store;
    }
    void destroySelfTest() throws Exception {
        if (!alias.startsWith("sheng_face_selftest_")
                || !metadata.getBaseFile().getCanonicalPath().contains("/sheng_face/self-test/")
                || !template.getBaseFile().getCanonicalPath().contains("/sheng_face/self-test/")) {
            throw new SecurityException("Only isolated self-test records may use this cleanup");
        }
        deleteKey(); metadata.delete(); template.delete();
        File de = metadata.getBaseFile().getParentFile(), ce = template.getBaseFile().getParentFile();
        if ((de.exists() && !de.delete()) || (ce.exists() && !ce.delete())) throw new IOException("Self-test cleanup failed");
    }
    private byte[] aad(String kind) {
        return ("ShengNativeFace:v1:user=" + user + ":" + kind + ":" + MODEL).getBytes(StandardCharsets.US_ASCII);
    }
    private byte[] read(AtomicFile file, String kind) throws Exception {
        byte[] packed;
        try (FileInputStream in = file.openRead()) {
            long size = in.getChannel().size();
            if (size < 36 || size > LIMIT) throw new IOException("Encrypted record length");
            packed = new byte[(int) size]; new DataInputStream(in).readFully(packed);
            if (in.read() != -1) throw new IOException("Record grew while reading");
        } catch (FileNotFoundException absent) { return null; }
        try (DataInputStream in = new DataInputStream(new ByteArrayInputStream(packed))) {
            if (in.readInt() != MAGIC) throw new IOException("Encrypted record magic");
            byte[] iv = new byte[12]; in.readFully(iv);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key(false), new GCMParameterSpec(128, iv)); cipher.updateAAD(aad(kind));
            return cipher.doFinal(packed, 16, packed.length - 16);
        } finally { Arrays.fill(packed, (byte) 0); }
    }
    private void write(AtomicFile file, String kind, byte[] plain) throws Exception {
        File dir = file.getBaseFile().getParentFile();
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("Private directory unavailable");
        Os.chmod(dir.getPath(), 0700);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key(true)); cipher.updateAAD(aad(kind));
        byte[] ciphertext = cipher.doFinal(plain), iv = cipher.getIV();
        if (iv.length != 12) throw new IOException("GCM IV length");
        FileOutputStream stream = null;
        try {
            stream = file.startWrite();
            Os.fchmod(stream.getFD(), 0600);
            DataOutputStream out = new DataOutputStream(stream);
            out.writeInt(MAGIC); out.write(iv); out.write(ciphertext); out.flush();
            file.finishWrite(stream); stream = null;
        } finally {
            if (stream != null) file.failWrite(stream);
            Arrays.fill(ciphertext, (byte) 0);
        }
    }
}
