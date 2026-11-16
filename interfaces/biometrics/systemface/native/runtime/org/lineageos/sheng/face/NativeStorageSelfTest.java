// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.face;

import android.content.Context;
import android.hardware.biometrics.face.Feature;
import android.os.SystemClock;
import android.os.UserManager;
import java.io.File;
import java.nio.file.Files;
import java.util.Arrays;
import javax.crypto.AEADBadTagException;

/** Synthetic encrypted records in a separate namespace; never formal enrollments. */
public final class NativeStorageSelfTest {
    private static int checks;
    private static void check(boolean value) { checks++; if (!value) throw new AssertionError("Storage check " + checks); }
    public static void run(Context context) throws Exception {
        String name = "t" + SystemClock.elapsedRealtime();
        File de = new File("/data/system_de/0/sheng_face/self-test/" + name),
                ce = new File("/data/system_ce/0/sheng_face/self-test/" + name);
        UserManager users = context.getSystemService(UserManager.class);
        EncryptedFaceRepository repo = new EncryptedFaceRepository(0,users,de,ce,"sheng_face_selftest_"+name);
        float[][] samples = new float[12][128]; for (float[] sample : samples) sample[0] = 1;
        byte[] encrypted = null, metadata = null;
        try {
            check(repo.enrollmentId() == 0 && repo.failures() == 0);
            repo.enroll(17,samples,new byte[] {Feature.REQUIRE_DIVERSE_POSES});
            check(repo.enrollmentId() == 17 && repo.features()[0] == Feature.REQUIRE_DIVERSE_POSES);
            float[][] restored = repo.load();
            try { check(restored.length == 12 && restored[0][0] == 1 && restored[0][1] == 0); }
            finally { for (float[] sample : restored) Arrays.fill(sample,0); }
            repo.failures(3);
            EncryptedFaceRepository restarted = new EncryptedFaceRepository(0,users,de,ce,"sheng_face_selftest_"+name);
            check(restarted.failures() == 3 && restarted.enrollmentId() == 17);
            File tf = new File(ce,"template.aesgcm"), mf = new File(de,"metadata.aesgcm");
            encrypted = Files.readAllBytes(tf.toPath()); metadata = Files.readAllBytes(mf.toPath());
            check(encrypted.length > 12*128*4 && metadata.length > 24);
            byte[] damaged = encrypted.clone(); damaged[damaged.length-1] ^= 1;
            Files.write(tf.toPath(),damaged); Arrays.fill(damaged,(byte)0);
            boolean tamper = false;
            try { repo.load(); } catch (AEADBadTagException expected) { tamper = true; }
            check(tamper); Files.write(tf.toPath(),encrypted);
            Files.write(mf.toPath(),encrypted);
            boolean kind = false;
            try { repo.enrollmentId(); } catch (AEADBadTagException expected) { kind = true; }
            check(kind); Files.write(mf.toPath(),metadata);
            EncryptedFaceRepository wrongUser = new EncryptedFaceRepository(12345,users,de,ce,"sheng_face_selftest_"+name);
            boolean binding = false;
            try { wrongUser.enrollmentId(); } catch (AEADBadTagException expected) { binding = true; }
            check(binding);
            repo.remove(); check(repo.enrollmentId() == 0 && !tf.exists() && repo.failures() == 3);
            Files.write(mf.toPath(),metadata); // Old ciphertext must not decrypt after key deletion/recreation.
            boolean shredded = false;
            try { repo.enrollmentId(); } catch (AEADBadTagException expected) { shredded = true; }
            check(shredded);
            repo.remove(); check(repo.enrollmentId() == 0 && repo.failures() == 5); // Corruption remains fail-closed.
            System.out.println("Encrypted native storage: " + checks + " checks passed; isolated synthetic records only");
        } finally {
            for (float[] sample : samples) Arrays.fill(sample,0);
            if (encrypted != null) Arrays.fill(encrypted,(byte)0);
            if (metadata != null) Arrays.fill(metadata,(byte)0);
            repo.destroySelfTest();
        }
    }
}
