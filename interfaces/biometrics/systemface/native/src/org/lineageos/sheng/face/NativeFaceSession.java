// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.face;

import android.hardware.biometrics.common.ICancellationSignal;
import android.hardware.biometrics.common.OperationContext;
import android.hardware.biometrics.face.AuthenticationFrame;
import android.hardware.biometrics.face.BaseFrame;
import android.hardware.biometrics.face.EnrollmentFrame;
import android.hardware.biometrics.face.EnrollmentStage;
import android.hardware.biometrics.face.EnrollmentStageConfig;
import android.hardware.biometrics.face.Error;
import android.hardware.biometrics.face.FaceEnrollOptions;
import android.hardware.biometrics.face.Feature;
import android.hardware.biometrics.face.ISession;
import android.hardware.biometrics.face.ISessionCallback;
import android.hardware.common.NativeHandle;
import android.hardware.keymaster.HardwareAuthToken;
import android.hardware.keymaster.Timestamp;
import android.os.Binder;
import android.os.Handler;
import android.os.IBinder;
import android.os.RemoteException;
import android.os.SystemClock;
import android.view.Surface;
import java.security.SecureRandom;
import java.util.Arrays;
import org.lineageos.sheng.facelab.FaceEmbedding;
import org.lineageos.sheng.facelab.MatchSession;
import org.lineageos.sheng.facelab.SampleCollector;

/** Standard, serialized Face V5 session. There is no trust-agent or Settings entry. */
public final class NativeFaceSession extends ISession.Stub {
    interface TokenVerifier { boolean verify(int user, HardwareAuthToken token); }
    interface Response { void send() throws RemoteException; }
    private static final int MAX_FAILURES = 5;
    private static final long ENROLL_TIMEOUT_MS = 60_000;
    private final int user;
    private final Handler worker;
    private final ISessionCallback callback;
    private final IBinder.DeathRecipient death;
    private final ChallengeLedger challenges;
    private final FaceRepository repository;
    private final FaceCapture capture;
    private final TokenVerifier verifier;
    private final Runnable released;
    private final SampleCollector collector = new SampleCollector(FaceEmbedding::validate);
    private final MatchSession match = new MatchSession();
    private final SecureRandom random = new SecureRandom();
    private long epoch;
    private boolean busy, closed;
    private float[][] references;

    public NativeFaceSession(int user, Handler worker, ISessionCallback callback,
            ChallengeLedger challenges, FaceRepository repository, FaceCapture capture,
            Runnable released) throws RemoteException {
        this(user, worker, callback, challenges, repository, capture,
                new CredentialTokenVerifier()::verifyForUser, released);
    }

    NativeFaceSession(int user, Handler worker, ISessionCallback callback,
            ChallengeLedger challenges, FaceRepository repository, FaceCapture capture,
            TokenVerifier verifier, Runnable released) throws RemoteException {
        this.user = user; this.worker = worker; this.callback = callback;
        this.challenges = challenges; this.repository = repository; this.capture = capture;
        this.verifier = verifier; this.released = released;
        death = () -> shutdown(false);
        callback.asBinder().linkToDeath(death, 0);
    }

    private static void caller() {
        if (Binder.getCallingUid() != android.os.Process.SYSTEM_UID) {
            throw new SecurityException("Face HAL is restricted to the system biometric service");
        }
    }

    private synchronized long reserve() {
        caller();
        if (closed || busy) {
            // The framework catches RemoteException, not marshalled unchecked
            // exceptions. Report transient protocol state through the HAL callback.
            busy = false; ++epoch;
            worker.post(() -> { cleanup(); respond(() -> callback.onError(Error.HW_UNAVAILABLE, 0)); });
            return -1;
        }
        busy = true; return ++epoch;
    }
    private synchronized boolean current(long operation) {
        return !closed && busy && epoch == operation;
    }
    private synchronized void startCapture(long op, boolean enrolling, Surface preview,
            boolean diverse, FaceCapture.Listener listener) throws Exception {
        // A cancellation winning this lock cannot start capture afterward.
        if (current(op)) capture.start(enrolling, preview, diverse, listener);
    }
    private void respond(Response response) {
        try { response.send(); } catch (RemoteException failure) { shutdown(false); }
    }
    private void terminal(long operation, Response response) {
        synchronized (this) {
            if (!current(operation)) return;
            busy = false; ++epoch;
        }
        cleanup(); respond(response);
    }
    private void fail(long operation, byte error) {
        if (current(operation)) android.util.Log.w("ShengNativeFace", "Session error=" + error);
        terminal(operation, () -> callback.onError(error, 0));
    }
    private void commit(long operation, Action write, Response response) throws Exception {
        // Cancellation and final persistence have one linearization point. A cancellation
        // that precedes this lock can never create a hidden enrollment or reset lockout.
        synchronized (this) {
            if (!current(operation)) return;
            write.run(operation); busy = false; ++epoch;
        }
        cleanup(); respond(response);
    }
    private void cleanup() {
        capture.stop(); collector.cancel(); match.cancel();
        wipe(references); references = null;
    }
    private static void wipe(float[][] samples) {
        if (samples != null) for (float[] row : samples) if (row != null) Arrays.fill(row, 0);
    }
    private void quick(Action action) {
        quick(action, () -> {});
    }
    private void quick(Action action, Runnable disposed) {
        long op = reserve();
        worker.post(() -> {
            try {
                if (current(op)) action.run(op);
            } catch (Exception | LinkageError failure) { fail(op, Error.UNABLE_TO_PROCESS); }
            finally { disposed.run(); }
        });
    }
    interface Action { void run(long op) throws Exception; }
    private ICancellationSignal signal(long op) {
        return new ICancellationSignal.Stub() {
            @Override public int getInterfaceVersion() { return ICancellationSignal.VERSION; }
            @Override public String getInterfaceHash() { return ICancellationSignal.HASH; }
            @Override public void cancel() {
                caller();
                // Invalidate immediately, before queued inference or callbacks can complete.
                final long cancellation;
                synchronized (NativeFaceSession.this) {
                    if (!current(op)) return;
                    cancellation = ++epoch;
                }
                worker.post(() -> {
                    cleanup();
                    synchronized (NativeFaceSession.this) {
                        if (closed || epoch != cancellation) return;
                        busy = false;
                    }
                    respond(() -> callback.onError(Error.CANCELED, 0));
                });
            }
        };
    }
    @Override public int getInterfaceVersion() { return ISession.VERSION; }
    @Override public String getInterfaceHash() { return ISession.HASH; }
    @Override public void generateChallenge() {
        quick(op -> { long c = challenges.generate(); terminal(op, () -> callback.onChallengeGenerated(c)); });
    }
    @Override public void revokeChallenge(long challenge) {
        quick(op -> { challenges.revoke(challenge); terminal(op, () -> callback.onChallengeRevoked(challenge)); });
    }
    @Override public EnrollmentStageConfig[] getEnrollmentConfig(byte enrollmentType) {
        caller(); return new EnrollmentStageConfig[0];
    }
    @Override public ICancellationSignal enroll(HardwareAuthToken hat, byte type, byte[] features,
            NativeHandle surface) {
        // Current V5 provides a true Surface. Never interpret legacy integer handles as Java surfaces.
        long op = reserve(); worker.post(() -> fail(op, Error.UNABLE_TO_PROCESS)); return signal(op);
    }
    @Override public ICancellationSignal enrollWithContext(HardwareAuthToken hat, byte type,
            byte[] features, NativeHandle surface, OperationContext context) {
        return enroll(hat, type, features, surface);
    }
    private static HardwareAuthToken snapshot(HardwareAuthToken token) {
        if (token == null || token.timestamp == null || token.mac == null) return null;
        HardwareAuthToken copy = new HardwareAuthToken();
        copy.challenge = token.challenge; copy.userId = token.userId;
        copy.authenticatorId = token.authenticatorId; copy.authenticatorType = token.authenticatorType;
        copy.timestamp = new Timestamp(); copy.timestamp.milliSeconds = token.timestamp.milliSeconds;
        copy.mac = token.mac.clone(); return copy;
    }
    @Override public ICancellationSignal enrollWithOptions(FaceEnrollOptions options) {
        long op = reserve();
        HardwareAuthToken hat = snapshot(options == null ? null : options.hardwareAuthToken);
        Surface preview = options == null ? null : options.surfacePreview;
        byte[] features = options == null || options.features == null ? new byte[0] : options.features.clone();
        worker.post(() -> {
            String phase = "credential";
            try {
                if (!current(op)) return;
                if (hat == null || preview == null || !preview.isValid()
                        || !challenges.valid(hat.challenge) || !verifier.verify(user, hat)
                        || !current(op) || !challenges.consume(hat.challenge)) {
                    fail(op, Error.UNABLE_TO_PROCESS); return;
                }
                android.util.Log.i("ShengNativeFace", "Hardware credential authorization verified for enrollment");
                phase = "repository";
                if (repository.enrollmentId() != 0) { fail(op, Error.NO_SPACE); return; }
                // Never silently accept a requested feature that the actual driver cannot supply.
                for (byte feature : features) {
                    if (feature != Feature.REQUIRE_DIVERSE_POSES || !capture.supportsDiversePoses()) {
                        android.util.Log.w("ShengNativeFace", "Unsupported enrollment feature=" + feature);
                        fail(op, Error.UNABLE_TO_PROCESS); return;
                    }
                }
                int id; do { id = random.nextInt(Integer.MAX_VALUE); } while (id == 0);
                final int enrollment = id;
                long collect = collector.begin();
                boolean diverse = features.length > 0;
                phase = "capture-start";
                startCapture(op, true, preview, diverse, new FaceCapture.Listener() {
                    @Override public void error(byte error) { worker.post(() -> fail(op, error)); }
                    @Override public void frame(long timestamp, float[] embedding, byte acquired, int vendorCode, byte stage,
                            float pan, float tilt) {
                        float[] owned = embedding == null ? null : embedding.clone();
                        worker.post(() -> {
                            try {
                                if (!current(op)) return;
                                EnrollmentFrame feedback = new EnrollmentFrame();
                                feedback.stage = stage;
                                feedback.data = frameData(acquired);
                                feedback.data.vendorCode = vendorCode;
                                feedback.data.pan = pan; feedback.data.tilt = tilt;
                                respond(() -> callback.onEnrollmentFrame(feedback));
                                if (!current(op) || owned == null || !collector.offer(collect, timestamp, owned)) return;
                                int remaining = SampleCollector.REQUIRED - collector.count();
                                if (remaining > 0) {
                                    respond(() -> callback.onEnrollmentProgress(enrollment, remaining)); return;
                                }
                                float[][] complete = collector.completed(collect);
                                try {
                                    if (!current(op) || complete == null) return;
                                    commit(op, ignored -> repository.enroll(enrollment, complete, features),
                                            () -> callback.onEnrollmentProgress(enrollment, 0));
                                } finally { wipe(complete); }
                            } catch (Exception | LinkageError failure) { fail(op, Error.UNABLE_TO_PROCESS); }
                            finally { if (owned != null) Arrays.fill(owned, 0); }
                        });
                    }
                });
                worker.postDelayed(() -> fail(op, Error.TIMEOUT), ENROLL_TIMEOUT_MS);
            } catch (Exception | LinkageError failure) {
                android.util.Log.e("ShengNativeFace", "Enrollment failed at " + phase + ": " + failure.getClass().getSimpleName());
                fail(op, Error.HW_UNAVAILABLE);
            }
            finally { if (hat != null) Arrays.fill(hat.mac, (byte) 0); }
        });
        return signal(op);
    }
    private static BaseFrame frameData(byte acquired) {
        BaseFrame data = new BaseFrame(); data.acquiredInfo = acquired; return data;
    }
    @Override public ICancellationSignal authenticate(long operationId) {
        long op = reserve();
        worker.post(() -> {
            try {
                if (!current(op)) return;
                if (operationId != 0) { fail(op, Error.UNABLE_TO_PROCESS); return; }
                if (repository.failures() >= MAX_FAILURES) {
                    terminal(op, callback::onLockoutPermanent); return;
                }
                int id = repository.enrollmentId(); references = repository.load();
                if (id == 0 || references == null || references.length != SampleCollector.REQUIRED) {
                    fail(op, Error.UNABLE_TO_PROCESS); return;
                }
                for (float[] sample : references) FaceEmbedding.validate(sample);
                long attempt = match.begin(SystemClock.elapsedRealtime());
                boolean[] evaluated = {false};
                startCapture(op, false, null, false, new FaceCapture.Listener() {
                    @Override public void error(byte error) { worker.post(() -> fail(op, error)); }
                    @Override public void frame(long timestamp, float[] embedding, byte acquired, int vendorCode, byte stage,
                            float pan, float tilt) {
                        float[] owned = embedding == null ? null : embedding.clone();
                        worker.post(() -> {
                            try {
                                if (!current(op)) return;
                                AuthenticationFrame feedback = new AuthenticationFrame();
                                feedback.data = frameData(acquired);
                                feedback.data.vendorCode = vendorCode;
                                feedback.data.pan = pan; feedback.data.tilt = tilt;
                                respond(() -> callback.onAuthenticationFrame(feedback));
                                if (!current(op)) return;
                                if (owned == null) { match.missing(attempt); return; }
                                evaluated[0] = true;
                                double score = 0;
                                for (float[] sample : references) score += FaceEmbedding.cosine(owned, sample);
                                if (!match.offer(attempt, SystemClock.elapsedRealtime(), timestamp,
                                        score / references.length) || !current(op)) return;
                                commit(op, ignored -> repository.failures(0),
                                        () -> callback.onAuthenticationSucceeded(id,
                                            NativeFaceTokens.absentAttestation()));
                            } catch (Exception | LinkageError failure) { fail(op, Error.UNABLE_TO_PROCESS); }
                            finally { if (owned != null) Arrays.fill(owned, 0); }
                        });
                    }
                });
                worker.postDelayed(() -> {
                    if (!current(op)) return;
                    if (!evaluated[0]) { fail(op, Error.TIMEOUT); return; }
                    try {
                        int failures = Math.min(MAX_FAILURES, repository.failures() + 1);
                        commit(op, ignored -> repository.failures(failures), failures >= MAX_FAILURES
                                ? callback::onLockoutPermanent : callback::onAuthenticationFailed);
                    } catch (Exception failure) { fail(op, Error.UNABLE_TO_PROCESS); }
                }, MatchSession.TIMEOUT_MS);
            } catch (Exception | LinkageError failure) { fail(op, Error.HW_UNAVAILABLE); }
        }); return signal(op);
    }
    @Override public ICancellationSignal authenticateWithContext(long id, OperationContext context) {
        return authenticate(id);
    }
    @Override public ICancellationSignal detectInteraction() {
        long op = reserve(); worker.post(() -> fail(op, Error.UNABLE_TO_PROCESS)); return signal(op);
    }
    @Override public ICancellationSignal detectInteractionWithContext(OperationContext context) {
        return detectInteraction();
    }
    @Override public void onContextChanged(OperationContext context) { caller(); }
    @Override public void enumerateEnrollments() {
        quick(op -> { int id = repository.enrollmentId(); terminal(op, () -> callback.onEnrollmentsEnumerated(
                id == 0 ? new int[0] : new int[] {id})); });
    }
    @Override public void removeEnrollments(int[] ids) {
        int[] requested = ids == null ? new int[0] : ids.clone();
        quick(op -> {
            int id;
            try { id = repository.enrollmentId(); }
            catch (Exception unreadable) {
                // This single-enrollment sensor can still erase an unusable record
                // when the system supplies its recorded positive ID. Repository
                // deletion preserves lockout and must succeed before the callback.
                if (requested.length != 1 || requested[0] <= 0) throw unreadable;
                commit(op, ignored -> repository.remove(),
                        () -> callback.onEnrollmentsRemoved(requested));
                return;
            }
            boolean found = false; for (int requestedId : requested) if (requestedId == id && id != 0) found = true;
            int[] removed = found ? new int[] {id} : new int[0];
            if (found) commit(op, ignored -> repository.remove(), () -> callback.onEnrollmentsRemoved(removed));
            else terminal(op, () -> callback.onEnrollmentsRemoved(removed));
        });
    }
    @Override public void getFeatures() {
        quick(op -> {
            if (repository.enrollmentId() == 0) { fail(op, Error.UNABLE_TO_PROCESS); return; }
            byte[] features = repository.features();
            terminal(op, () -> callback.onFeaturesRetrieved(features));
        });
    }
    @Override public void setFeature(HardwareAuthToken token, byte feature, boolean enabled) {
        HardwareAuthToken hat = snapshot(token);
        quick(op -> {
            try {
                if (repository.enrollmentId() == 0 || enabled || feature != Feature.REQUIRE_ATTENTION
                        || !verifier.verify(user, hat)) { fail(op, Error.UNABLE_TO_PROCESS); return; }
                terminal(op, () -> callback.onFeatureSet(feature));
            } finally { if (hat != null) Arrays.fill(hat.mac, (byte) 0); }
        }, () -> { if (hat != null) Arrays.fill(hat.mac, (byte) 0); });
    }
    @Override public void getAuthenticatorId() {
        quick(op -> terminal(op, () -> callback.onAuthenticatorIdRetrieved(0)));
    }
    @Override public void invalidateAuthenticatorId() {
        quick(op -> terminal(op, () -> callback.onAuthenticatorIdInvalidated(0)));
    }
    @Override public void resetLockout(HardwareAuthToken token) {
        HardwareAuthToken hat = snapshot(token);
        quick(op -> {
            try {
                if (!verifier.verify(user, hat)) { fail(op, Error.UNABLE_TO_PROCESS); return; }
                commit(op, ignored -> repository.failures(0), callback::onLockoutCleared);
            } finally { if (hat != null) Arrays.fill(hat.mac, (byte) 0); }
        }, () -> { if (hat != null) Arrays.fill(hat.mac, (byte) 0); });
    }
    @Override public void close() {
        caller();
        // Closing is itself a cancellation barrier, including while capture is busy.
        shutdown(true);
    }
    // A replacement must not deliver an old onSessionClosed into the new
    // framework session; invalidate capture and retire the old callback silently.
    void retire() { shutdown(false); }
    private void shutdown(boolean notify) {
        synchronized (this) { if (closed) return; closed = true; busy = false; ++epoch; }
        worker.post(() -> {
            cleanup(); callback.asBinder().unlinkToDeath(death, 0); released.run();
            if (notify) respond(callback::onSessionClosed);
        });
    }
}
