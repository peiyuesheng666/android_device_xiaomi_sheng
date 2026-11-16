// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.face;

import android.hardware.biometrics.common.CommonProps;
import android.hardware.biometrics.common.ComponentInfo;
import android.hardware.biometrics.common.SensorStrength;
import android.hardware.biometrics.face.FaceSensorType;
import android.hardware.biometrics.face.Error;
import android.hardware.biometrics.face.IFace;
import android.hardware.biometrics.face.ISession;
import android.hardware.biometrics.face.ISessionCallback;
import android.hardware.biometrics.face.SensorProps;
import android.os.Binder;
import android.os.Handler;
import android.os.Process;
import android.os.RemoteException;
import android.os.SystemClock;
import java.security.SecureRandom;
import java.util.HashMap;
import java.util.Map;

/** Source-owned provider for the original FaceService, Settings and Keyguard. */
public final class NativeFaceProvider extends IFace.Stub {
    public static final int SENSOR_ID = 1; // Fingerprint uses sensor 0 on sheng.
    public interface Factory {
        FaceRepository repository(int user) throws Exception;
        FaceCapture capture(int user) throws Exception;
    }
    private final Handler worker;
    private final Factory factory;
    private final Map<Integer, ChallengeLedger> challenges = new HashMap<>();
    private NativeFaceSession active;

    public NativeFaceProvider(Handler worker, Factory factory) {
        this.worker = worker; this.factory = factory;
    }
    private static void caller() {
        if (Binder.getCallingUid() != Process.SYSTEM_UID) throw new SecurityException("System caller required");
    }
    @Override public int getInterfaceVersion() { return IFace.VERSION; }
    @Override public String getInterfaceHash() { return IFace.HASH; }
    @Override public SensorProps[] getSensorProps() {
        caller();
        SensorProps p = new SensorProps(); p.commonProps = new CommonProps();
        p.commonProps.sensorId = SENSOR_ID;
        p.commonProps.sensorStrength = SensorStrength.CONVENIENCE;
        p.commonProps.maxEnrollmentsPerUser = 1;
        ComponentInfo engine = new ComponentInfo();
        engine.componentId = "sheng-software-face"; engine.hardwareVersion = "front-rgb";
        engine.firmwareVersion = "none"; engine.softwareVersion = "OpenCV-4.13.0-SFace";
        engine.serialNumber = "";
        p.commonProps.componentInfo = new ComponentInfo[] {engine};
        p.sensorType = FaceSensorType.RGB; p.halControlsPreview = true;
        p.previewDisplayId = 0; p.enrollPreviewWidth = 1280; p.enrollPreviewHeight = 960;
        p.enrollPreviewScale = 1.0f; p.supportsDetectInteraction = false;
        return new SensorProps[] {p};
    }
    @Override public synchronized ISession createSession(int sensor, int user, ISessionCallback callback)
            throws RemoteException {
        caller();
        if (sensor != SENSOR_ID || user < 0 || callback == null) throw new IllegalArgumentException("Invalid session");
        if (active != null) { active.retire(); active = null; }
        // Challenge authority belongs to (sensor,user), surviving scheduler session switches.
        ChallengeLedger ledger = challenges.computeIfAbsent(user,
                ignored -> new ChallengeLedger(new SecureRandom(), SystemClock::elapsedRealtime));
        NativeFaceSession[] created = new NativeFaceSession[1];
        FaceRepository repository;
        FaceCapture capture;
        try {
            repository = factory.repository(user); capture = factory.capture(user);
            if (repository == null || capture == null) throw new IllegalStateException("Missing backend");
        }
        catch (Exception | LinkageError unavailable) {
            android.util.Log.w("ShengNativeFace", "User backend is unavailable; returning an error-only session");
            repository = new FaceRepository() {
                private Exception unavailable() { return new java.io.IOException("User backend unavailable"); }
                @Override public int enrollmentId() throws Exception { throw unavailable(); }
                @Override public float[][] load() throws Exception { throw unavailable(); }
                @Override public void enroll(int id, float[][] samples, byte[] features) throws Exception { throw unavailable(); }
                @Override public byte[] features() throws Exception { throw unavailable(); }
                @Override public void remove() throws Exception { throw unavailable(); }
                @Override public int failures() throws Exception { throw unavailable(); }
                @Override public void failures(int count) throws Exception { throw unavailable(); }
            };
            capture = new FaceCapture() {
                @Override public void start(boolean enrolling, android.view.Surface preview,
                        boolean diverse, Listener listener) { listener.error(Error.HW_UNAVAILABLE); }
                @Override public void stop() {}
            };
        }
        created[0] = new NativeFaceSession(user, worker, callback, ledger,
                    repository, capture, () -> {
                        synchronized (NativeFaceProvider.this) { if (active == created[0]) active = null; }
                    });
        active = created[0]; return active;
    }
}
