// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.face;

import android.hardware.biometrics.common.ICancellationSignal;
import android.hardware.biometrics.face.AcquiredInfo;
import android.hardware.biometrics.face.AuthenticateSuccess;
import android.hardware.biometrics.face.AuthenticationFrame;
import android.hardware.biometrics.face.EnrollmentFrame;
import android.hardware.biometrics.face.Error;
import android.hardware.biometrics.face.ISessionCallback;
import android.hardware.biometrics.face.IFace;
import android.hardware.biometrics.face.ISession;
import android.os.Binder;
import android.os.Parcel;
import android.os.RemoteException;
import android.hardware.keymaster.HardwareAuthToken;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.Process;
import android.view.Surface;
import java.security.SecureRandom;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Synthetic session protocol tests. No service registration, camera, images or real templates. */
public final class NativeFaceSessionProbe {
    private static int checks;
    private static void check(boolean condition) { checks++; if (!condition) throw new AssertionError("Session check " + checks); }
    private static void drain(Handler worker) throws Exception {
        CountDownLatch gate = new CountDownLatch(1); worker.post(gate::countDown);
        check(gate.await(3, TimeUnit.SECONDS));
    }
    private static float[] embedding(double cosine) {
        float[] v = new float[128]; v[0] = (float) cosine;
        v[1] = (float) Math.sqrt(1 - cosine * cosine); return v;
    }
    private static final class Repository implements FaceRepository {
        int id = 12, failures = 0;
        boolean unreadable;
        @Override public int enrollmentId() throws Exception {
            if (unreadable) throw new java.io.IOException("Synthetic unreadable metadata");
            return id;
        }
        @Override public float[][] load() {
            if (id == 0) return null;
            float[][] result = new float[12][];
            for (int i = 0; i < result.length; i++) result[i] = embedding(1); return result;
        }
        @Override public void enroll(int id, float[][] samples, byte[] features) { throw new AssertionError("No enrollment permitted in protocol tests"); }
        @Override public byte[] features() { return new byte[0]; }
        @Override public void remove() { id = 0; unreadable = false; }
        @Override public int failures() { return failures; }
        @Override public void failures(int failures) { this.failures = failures; }
    }
    private static final class Capture implements FaceCapture {
        Listener listener;
        int starts, stops;
        @Override public void start(boolean enrolling, Surface preview, boolean diverse, Listener listener) {
            check(!enrolling && preview == null); starts++; this.listener = listener;
        }
        @Override public void stop() { stops++; }
    }
    private static final class Callback extends ISessionCallback.Stub {
        int successes, canceled, errors, lockouts, closed;
        byte lastError;
        CountDownLatch timeout;
        int[] enumerated, removed;
        long challenge, authenticator = -1;
        @Override public int getInterfaceVersion() { return VERSION; }
        @Override public String getInterfaceHash() { return HASH; }
        @Override public void onChallengeGenerated(long c) { challenge = c; }
        @Override public void onChallengeRevoked(long c) {}
        @Override public void onAuthenticationFrame(AuthenticationFrame frame) {}
        @Override public void onEnrollmentFrame(EnrollmentFrame frame) { throw new AssertionError("No enrollment frames allowed"); }
        @Override public void onError(byte error, int vendor) {
            errors++; lastError = error; if (error == Error.CANCELED) canceled++;
            if (error == Error.TIMEOUT && timeout != null) timeout.countDown();
        }
        @Override public void onEnrollmentProgress(int id, int remaining) { throw new AssertionError("No enrollment success allowed"); }
        @Override public void onAuthenticationSucceeded(int id, HardwareAuthToken hat) {
            check(id == 12 && hat.mac.length == 0 && hat.userId == 0 && hat.authenticatorType == 0);
            successes++;
        }
        @Override public void onAuthenticationSucceededWithResult(AuthenticateSuccess result) { throw new AssertionError("Unexpected result variant"); }
        @Override public void onAuthenticationFailed() { throw new AssertionError("Unexpected timeout in fast tests"); }
        @Override public void onLockoutTimed(long duration) { throw new AssertionError("No timed lockout"); }
        @Override public void onLockoutPermanent() { lockouts++; }
        @Override public void onLockoutCleared() { throw new AssertionError("Invalid HAT cannot clear lockout"); }
        @Override public void onInteractionDetected() { throw new AssertionError("Interaction is unsupported"); }
        @Override public void onEnrollmentsEnumerated(int[] ids) { enumerated = ids; }
        @Override public void onFeaturesRetrieved(byte[] features) {}
        @Override public void onFeatureSet(byte feature) {}
        @Override public void onEnrollmentsRemoved(int[] ids) { removed = ids; }
        @Override public void onAuthenticatorIdRetrieved(long id) { authenticator = id; }
        @Override public void onAuthenticatorIdInvalidated(long id) { authenticator = id; }
        @Override public void onSessionClosed() { closed++; }
    }
    public static void main(String[] args) throws Exception {
        if (Process.myUid() == 0) { Process.setGid(1000); Process.setUid(1000); }
        check(Process.myUid() == 1000);
        HandlerThread thread = new HandlerThread("native-face-synthetic-tests"); thread.start();
        Handler worker = new Handler(thread.getLooper());
        try {
            Repository repo = new Repository(); Capture capture = new Capture(); Callback cb = new Callback();
            ChallengeLedger ledger = new ChallengeLedger(new SecureRandom(), android.os.SystemClock::elapsedRealtime);
            int[] releases = {0};
            NativeFaceSession s = new NativeFaceSession(0, worker, cb, ledger, repo, capture,
                    (user, hat) -> false, () -> releases[0]++);
            s.generateChallenge(); drain(worker); long c1 = cb.challenge;
            s.generateChallenge(); drain(worker); check(ledger.valid(c1) && ledger.valid(cb.challenge));
            s.revokeChallenge(c1); drain(worker); check(!ledger.valid(c1));
            s.getAuthenticatorId(); drain(worker); check(cb.authenticator == 0);
            s.invalidateAuthenticatorId(); drain(worker); check(cb.authenticator == 0);
            s.enumerateEnrollments(); drain(worker); check(cb.enumerated.length == 1 && cb.enumerated[0] == 12);
            s.authenticate(1); drain(worker); check(capture.starts == 0 && cb.errors == 1);
            CountDownLatch blocked = new CountDownLatch(1), unblock = new CountDownLatch(1);
            worker.post(() -> {
                blocked.countDown();
                try { check(unblock.await(3, TimeUnit.SECONDS)); }
                catch (InterruptedException interrupted) { throw new AssertionError(interrupted); }
            });
            check(blocked.await(3, TimeUnit.SECONDS));
            ICancellationSignal queued = s.authenticate(0); queued.cancel(); unblock.countDown();
            drain(worker); check(capture.starts == 0 && cb.canceled == 1);
            ICancellationSignal first = s.authenticate(0); drain(worker);
            FaceCapture.Listener stale = capture.listener;
            int errorsBeforeBusyCall = cb.errors;
            s.enumerateEnrollments(); drain(worker);
            check(cb.errors == errorsBeforeBusyCall + 1 && cb.lastError == Error.HW_UNAVAILABLE);
            first.cancel(); first.cancel(); drain(worker); check(cb.canceled == 1 && cb.successes == 0);
            s.authenticate(0); drain(worker);
            for (int i = 0; i < 3; i++) stale.frame(i * 100_000_000L, embedding(1), AcquiredInfo.GOOD, 0, (byte)0, 0, 0);
            drain(worker); check(cb.successes == 0);
            // Exactly 0.5 is never accepted. Then three correctly spaced matches can succeed.
            for (int i = 0; i < 3; i++) capture.listener.frame(i * 100_000_000L, embedding(.5), AcquiredInfo.GOOD, 0, (byte)0, 0, 0);
            drain(worker); check(cb.successes == 0);
            for (int i = 3; i < 6; i++) capture.listener.frame(i * 100_000_000L, embedding(1), AcquiredInfo.GOOD, 0, (byte)0, 0, 0);
            drain(worker); check(cb.successes == 1 && repo.failures == 0);
            for (int i = 6; i < 9; i++) capture.listener.frame(i * 100_000_000L, embedding(1), AcquiredInfo.GOOD, 0, (byte)0, 0, 0);
            drain(worker); check(cb.successes == 1); // Exactly one terminal callback.
            cb.timeout = new CountDownLatch(1);
            s.authenticate(0); drain(worker);
            check(cb.timeout.await(7, TimeUnit.SECONDS)); drain(worker);
            check(cb.lastError == Error.TIMEOUT && repo.failures == 0); // No face is not an identity rejection.
            repo.failures = 5;
            s.resetLockout(NativeFaceTokens.absentAttestation()); drain(worker); check(repo.failures == 5);
            int starts = capture.starts;
            s.authenticate(0); drain(worker); check(cb.lockouts == 1 && capture.starts == starts);
            s.close(); drain(worker); check(cb.closed == 1 && releases[0] == 1);
            s.close(); drain(worker); check(cb.closed == 1); // Idempotent close.
            Callback cb2 = new Callback();
            NativeFaceSession afterRestart = new NativeFaceSession(0, worker, cb2, ledger, repo, capture,
                    (user, hat) -> false, () -> releases[0]++);
            afterRestart.authenticate(0); drain(worker); check(cb2.lockouts == 1 && capture.starts == starts);
            afterRestart.removeEnrollments(new int[] {99}); drain(worker); check(repo.id == 12 && cb2.removed.length == 0);
            afterRestart.removeEnrollments(new int[] {12}); drain(worker); check(repo.id == 0 && cb2.removed.length == 1);
            afterRestart.enumerateEnrollments(); drain(worker); check(cb2.enumerated.length == 0);
            repo.id = 12; repo.unreadable = true;
            afterRestart.removeEnrollments(new int[] {12}); drain(worker);
            check(repo.id == 0 && !repo.unreadable && repo.failures == 5 && cb2.removed[0] == 12);
            afterRestart.close(); drain(worker);
            repo.id = 12; repo.failures = 0;
            Callback closing = new Callback();
            NativeFaceSession busyClose = new NativeFaceSession(0, worker, closing, ledger, repo, capture,
                    (user, hat) -> false, () -> releases[0]++);
            busyClose.authenticate(0); drain(worker);
            FaceCapture.Listener closedFrames = capture.listener;
            busyClose.close(); drain(worker); check(closing.closed == 1);
            for (int i = 0; i < 3; i++) closedFrames.frame(i*100_000_000L,embedding(1),AcquiredInfo.GOOD,0,(byte)0,0,0);
            drain(worker); check(closing.successes == 0);
            NativeFaceProvider provider = new NativeFaceProvider(worker,new NativeFaceProvider.Factory() {
                @Override public FaceRepository repository(int user) { return repo; }
                @Override public FaceCapture capture(int user) { return capture; }
            });
            // Force IFace's Parcel/Proxy route, as FaceStartUserClient uses in system_server.
            IFace remote = IFace.Stub.asInterface(new Binder() {
                @Override protected boolean onTransact(int code, Parcel data, Parcel reply, int flags) throws RemoteException {
                    return provider.asBinder().transact(code,data,reply,flags);
                }
            });
            Callback old = new Callback(), replacement = new Callback();
            ISession oldSession = remote.createSession(1,0,old);
            oldSession.authenticate(0); drain(worker);
            FaceCapture.Listener replacedFrames = capture.listener;
            ISession newSession = remote.createSession(1,0,replacement); drain(worker);
            check(old.closed == 0 && newSession != null);
            for (int i=0;i<3;i++) replacedFrames.frame(i*100_000_000L,embedding(1),AcquiredInfo.GOOD,0,(byte)0,0,0);
            drain(worker); check(old.successes == 0 && replacement.successes == 0);
            newSession.enumerateEnrollments(); drain(worker); check(replacement.enumerated[0] == 12);
            newSession.close(); drain(worker);
            NativeFaceProvider unavailable = new NativeFaceProvider(worker,new NativeFaceProvider.Factory() {
                @Override public FaceRepository repository(int user) throws Exception { throw new java.io.IOException("Synthetic backend unavailable"); }
                @Override public FaceCapture capture(int user) { return capture; }
            });
            IFace unavailableRemote = IFace.Stub.asInterface(new Binder() {
                @Override protected boolean onTransact(int code, Parcel data, Parcel reply, int flags) throws RemoteException {
                    return unavailable.asBinder().transact(code,data,reply,flags);
                }
            });
            Callback failedBackend = new Callback();
            ISession errorSession = unavailableRemote.createSession(1,0,failedBackend);
            errorSession.enumerateEnrollments(); drain(worker);
            check(failedBackend.errors == 1 && failedBackend.enumerated == null && failedBackend.successes == 0);
            errorSession.close(); drain(worker); check(failedBackend.closed == 1);
            System.out.println("Synthetic native session: " + checks + " checks passed; camera not opened");
            System.out.println("This exercises a test-only repository/capture/verifier; it is not hardware enrollment acceptance");
        } finally { thread.quitSafely(); thread.join(3000); }
    }
}
