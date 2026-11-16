// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.facelab;

import android.app.KeyguardManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.graphics.ImageFormat;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.Image;
import android.media.ImageReader;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.PersistableBundle;
import android.os.PowerManager;
import android.os.SystemClock;
import android.os.UserHandle;
import android.os.UserManager;
import android.service.trust.TrustAgentService;
import android.util.Size;
import android.view.Surface;
import com.android.internal.widget.LockPatternUtils;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.io.FileDescriptor;
import java.io.PrintWriter;
import java.util.concurrent.atomic.AtomicLong;

/** Software lock-screen recognition through the platform's renewable trust mechanism. */
public final class FaceUnlockService extends TrustAgentService {
    private final AtomicLong epoch = new AtomicLong();
    private final MatchSession match = new MatchSession();
    private HandlerThread thread;
    private Handler worker;
    private KeyguardManager keyguard;
    private LockPatternUtils lock;
    private SharedPreferences preferences;
    private volatile boolean destroyed, armed, policyBlocked;
    private volatile long requestDeadline;
    private volatile boolean dismissRequested;
    // Camera, models, features and attempt state belong to worker.
    private CameraDevice camera;
    private CameraCaptureSession session;
    private ImageReader reader;
    private OpenCvEngine engine;
    private float[][] samples;
    private long attempt, started;
    private boolean evaluated;
    private int rotation, displayRotation;
    private volatile String state = "idle";
    private final BroadcastReceiver screen = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            if (Intent.ACTION_SCREEN_OFF.equals(intent.getAction())) stopAttempt();
            else if (Intent.ACTION_SCREEN_ON.equals(intent.getAction())) recognize(false);
        }
    };

    @Override public void onCreate() {
        super.onCreate();
        keyguard = getSystemService(KeyguardManager.class);
        lock = new LockPatternUtils(this);
        preferences = getSharedPreferences(FaceUnlockSettings.PREFS, MODE_PRIVATE);
        thread = new HandlerThread("FaceUnlock-capture"); thread.start();
        worker = new Handler(thread.getLooper());
        IntentFilter filter = new IntentFilter(Intent.ACTION_SCREEN_ON); filter.addAction(Intent.ACTION_SCREEN_OFF);
        registerReceiver(screen, filter, Context.RECEIVER_NOT_EXPORTED);
        setManagingTrust(available()); armAfterCredential();
    }
    private boolean available() {
        try {
        if (destroyed || policyBlocked || !FaceUnlockSettings.supported() || !FaceUnlockSettings.enabled(this)) return false;
        int disabled = getSystemService(android.app.admin.DevicePolicyManager.class)
                .getKeyguardDisabledFeatures(null);
        if ((disabled & (android.app.admin.DevicePolicyManager.KEYGUARD_DISABLE_TRUST_AGENTS
                | android.app.admin.DevicePolicyManager.KEYGUARD_DISABLE_FACE
                | android.app.admin.DevicePolicyManager.KEYGUARD_DISABLE_BIOMETRICS)) != 0) return false;
        boolean privacy = android.os.Build.VERSION.SDK_INT >= 31
                && getSystemService(android.hardware.SensorPrivacyManager.class)
                .isSensorPrivacyEnabled(android.hardware.SensorPrivacyManager.Sensors.CAMERA);
        int cameraMode = getSystemService(android.app.AppOpsManager.class).checkOpNoThrow(
                android.app.AppOpsManager.OPSTR_CAMERA, android.os.Process.myUid(), getPackageName());
        return !destroyed && !policyBlocked && !privacy
                && checkSelfPermission(android.Manifest.permission.CAMERA) == android.content.pm.PackageManager.PERMISSION_GRANTED
                && (cameraMode == android.app.AppOpsManager.MODE_ALLOWED
                    || cameraMode == android.app.AppOpsManager.MODE_FOREGROUND)
                && FaceUnlockSettings.enabled(this)
                && getSystemService(UserManager.class).isUserUnlocked()
                && keyguard.isDeviceSecure() && lock.getStrongAuthForUser(UserHandle.myUserId()) == 0
                && preferences.getInt("failed_attempts", 0) < 5;
        } catch (RuntimeException | LinkageError unavailable) { return false; }
    }
    private void armAfterCredential() {
        if (armed || !available() || keyguard.isDeviceLocked()) return;
        // Android 17 only permits renewable trust to unlock a locked device
        // after trust was established while credentials already unlocked it.
        float[][] checked = null;
        try {
            checked = new TemplateStore(this, true).load();
            if (checked == null) return;
            setManagingTrust(true); armed = true;
            grantTrust("FaceUnlock", 0, FLAG_GRANT_TRUST_TEMPORARY_AND_RENEWABLE);
            state = "armed-after-credential";
        } catch (Exception failure) { armed = false; setManagingTrust(false); }
        finally { wipe(checked); }
    }
    @Override public void onUnlockAttempt(boolean successful) {
        if (!successful) return;
        preferences.edit().putInt("failed_attempts", 0).commit();
        setManagingTrust(available()); armAfterCredential();
    }
    @Override public void onDeviceUnlocked() { stopAttempt(); armAfterCredential(); }
    @Override public void onDeviceLocked() { stopAttempt(); }
    @Override public void onUserRequestedUnlock(boolean dismissKeyguard) { recognize(dismissKeyguard); }
    @Override public void onTrustTimeout() { armed = false; stopAttempt(); state = "credential-required"; }
    @Override public void onDeviceUnlockLockout(long timeoutMs) {
        armed = false; stopAttempt(); revokeTrust();
    }
    @Override public boolean onConfigure(List<PersistableBundle> options) {
        policyBlocked = !options.isEmpty();
        if (policyBlocked) { armed = false; stopAttempt(); revokeTrust(); }
        setManagingTrust(available());
        return false; // No custom device-policy configuration is implemented.
    }
    private void recognize(boolean dismiss) {
        if (!armed || !available() || !keyguard.isDeviceLocked()
                || !getSystemService(PowerManager.class).isInteractive()) return;
        // Screen-on broadcasts must not downgrade an explicit system dismissal request.
        if (dismissRequested && SystemClock.elapsedRealtime() < requestDeadline) return;
        long token = epoch.incrementAndGet(); match.cancel();
        dismissRequested = dismiss;
        requestDeadline = SystemClock.elapsedRealtime() + MatchSession.TIMEOUT_MS;
        worker.post(() -> start(token, dismiss));
    }
    private boolean current(long token) {
        return token == epoch.get() && SystemClock.elapsedRealtime() < requestDeadline
                && armed && available() && keyguard.isDeviceLocked()
                && getSystemService(PowerManager.class).isInteractive();
    }
    private void start(long token, boolean dismiss) {
        close();
        if (!current(token)) return;
        try {
            samples = new TemplateStore(this, true).load();
            if (samples == null) return;
            evaluated = false; started = SystemClock.elapsedRealtime(); attempt = match.begin(started);
            state = "recognizing";
            long attemptToken = attempt;
            worker.postDelayed(() -> {
                if (token == epoch.get() && attempt == attemptToken) {
                    if (evaluated) failed();
                    stopAttempt();
                }
            }, MatchSession.TIMEOUT_MS);
            if (engine == null) engine = new OpenCvEngine(this);
            if (!current(token)) { close(); return; }
            CameraManager manager = getSystemService(CameraManager.class);
            String front = null; Size selected = null;
            for (String id : manager.getCameraIdList()) {
                CameraCharacteristics c = manager.getCameraCharacteristics(id);
                if (FaceLabActivity.isInternalCamera(c)) continue;
                if (!Integer.valueOf(CameraCharacteristics.LENS_FACING_FRONT).equals(c.get(CameraCharacteristics.LENS_FACING))) continue;
                Integer degrees = c.get(CameraCharacteristics.SENSOR_ORIENTATION);
                if (degrees == null) continue;
                displayRotation = getSystemService(android.hardware.display.DisplayManager.class)
                        .getDisplay(0).getRotation();
                int displayDegrees = displayRotation * 90;
                rotation = FrameMath.rotation(degrees, displayDegrees);
                StreamConfigurationMap streams = c.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
                if (streams == null) continue;
                long best = Long.MAX_VALUE;
                Size[] sizes = streams.getOutputSizes(ImageFormat.YUV_420_888);
                if (sizes == null) continue;
                for (Size size : sizes) {
                    if (size.getWidth() < 320 || size.getHeight() < 240 || size.getWidth() > 1280 || size.getHeight() > 960) continue;
                    long cost = Math.abs((long)size.getWidth()*size.getHeight() - 1280*960);
                    if (cost < best) { selected = size; best = cost; }
                }
                if (selected != null) { front = id; break; }
            }
            if (front == null || selected == null) { close(); return; }
            reader = ImageReader.newInstance(selected.getWidth(), selected.getHeight(), ImageFormat.YUV_420_888, 3);
            reader.setOnImageAvailableListener(input -> frame(input, token, dismiss), worker);
            manager.openCamera(front, new CameraDevice.StateCallback() {
                @Override public void onOpened(CameraDevice device) {
                    if (!current(token)) { device.close(); return; }
                    camera = device;
                    try {
                        Surface output = reader.getSurface();
                        device.createCaptureSession(Collections.singletonList(output), new CameraCaptureSession.StateCallback() {
                            @Override public void onConfigured(CameraCaptureSession configured) {
                                if (!current(token)) { configured.close(); return; }
                                session = configured;
                                try {
                                    CaptureRequest.Builder request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
                                    request.addTarget(output);
                                    request.set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_AUTO);
                                    request.set(CaptureRequest.STATISTICS_FACE_DETECT_MODE, CaptureRequest.STATISTICS_FACE_DETECT_MODE_OFF);
                                    if (android.os.Build.VERSION.SDK_INT >= 31) {
                                        int[] modes = manager.getCameraCharacteristics(device.getId())
                                                .get(CameraCharacteristics.SCALER_AVAILABLE_ROTATE_AND_CROP_MODES);
                                        if (modes != null) for (int mode : modes) if (mode == CaptureRequest.SCALER_ROTATE_AND_CROP_NONE) {
                                            request.set(CaptureRequest.SCALER_ROTATE_AND_CROP, mode); break;
                                        }
                                    }
                                    configured.setRepeatingRequest(request.build(), null, worker);
                                } catch (Exception failure) { if (token == epoch.get()) close(); }
                            }
                            @Override public void onConfigureFailed(CameraCaptureSession configured) {
                                configured.close(); if (token == epoch.get()) close();
                            }
                        }, worker);
                    } catch (Exception failure) { if (token == epoch.get()) close(); }
                }
                @Override public void onDisconnected(CameraDevice device) { device.close(); if (token == epoch.get()) close(); }
                @Override public void onError(CameraDevice device, int error) { device.close(); if (token == epoch.get()) close(); }
            }, worker);
        } catch (Exception | LinkageError failure) { close(); }
    }
    private void frame(ImageReader input, long token, boolean dismiss) {
        OpenCvEngine.Frame captured = null; long timestamp;
        try (Image image = input.acquireLatestImage()) {
            if (image == null) return;
            if (!current(token)) {
                if (token == epoch.get()) {
                    if (evaluated && SystemClock.elapsedRealtime() >= requestDeadline) failed();
                    stopAttempt(); // Release promptly on privacy, permission, lock or timeout changes.
                }
                return;
            }
            if (!match.active(attempt, SystemClock.elapsedRealtime())) return;
            if (getSystemService(android.hardware.display.DisplayManager.class).getDisplay(0).getRotation()
                    != displayRotation) { stopAttempt(); return; }
            timestamp = image.getTimestamp(); captured = OpenCvEngine.capture(image);
        } catch (Exception failure) { if (token == epoch.get()) close(); return; }
        OpenCvEngine.Result result = null;
        try {
            if (!current(token)) return;
            result = engine.analyze(captured, rotation, true, false);
            if (!current(token)) return;
            if (result.embedding == null) { match.missing(attempt); return; }
            evaluated = true;
            double sum = 0;
            for (float[] sample : samples) sum += FaceEmbedding.cosine(result.embedding, sample);
            if (!match.offer(attempt, SystemClock.elapsedRealtime(), timestamp, sum / samples.length)) return;
            if (!current(token)) return;
            evaluated = false; // A valid match must not become a failure in the expiry callback.
            preferences.edit().putInt("failed_attempts", 0).commit();
            int flags = FLAG_GRANT_TRUST_TEMPORARY_AND_RENEWABLE;
            if (dismiss) flags |= FLAG_GRANT_TRUST_INITIATED_BY_USER | FLAG_GRANT_TRUST_DISMISS_KEYGUARD;
            final int grantFlags = flags;
            final long deadline = started + MatchSession.TIMEOUT_MS;
            new Handler(getMainLooper()).post(() -> {
                if (current(token) && SystemClock.elapsedRealtime() < deadline) {
                    grantTrust("FaceUnlock", 0, grantFlags); state = "matched";
                }
            });
            close();
        } catch (Exception | LinkageError failure) { if (token == epoch.get()) close(); }
        finally {
            if (captured != null) captured.clear();
            if (result != null && result.embedding != null) Arrays.fill(result.embedding, 0);
        }
    }
    private void failed() {
        int failures = Math.min(5, preferences.getInt("failed_attempts", 0) + 1);
        if (!preferences.edit().putInt("failed_attempts", failures).commit() || failures >= 5) {
            armed = false;
            state = "credential-required";
            new Handler(getMainLooper()).post(() -> {
                if (!armed) { setManagingTrust(false); revokeTrust(); }
            });
        }
    }
    private void stopAttempt() {
        epoch.incrementAndGet(); requestDeadline = 0; dismissRequested = false;
        match.cancel(); if (worker != null) worker.post(this::close);
    }
    private static void wipe(float[][] features) { if (features != null) for (float[] f : features) Arrays.fill(f, 0); }
    private void close() {
        match.cancel();
        if (session != null) { session.close(); session = null; }
        if (camera != null) { camera.close(); camera = null; }
        if (reader != null) { reader.close(); reader = null; }
        wipe(samples); samples = null;
        if ("recognizing".equals(state)) state = "idle";
    }
    @Override protected void dump(FileDescriptor fd, PrintWriter out, String[] args) {
        if (checkCallingOrSelfPermission(android.Manifest.permission.DUMP)
                != android.content.pm.PackageManager.PERMISSION_GRANTED) return;
        out.println("FaceUnlock state=" + state + " armed=" + armed + " available=" + available());
        out.println("credentialRequired=" + (preferences.getInt("failed_attempts", 0) >= 5)
                + " policyBlocked=" + policyBlocked);
    }
    @Override public void onDestroy() {
        destroyed = true; armed = false; stopAttempt(); unregisterReceiver(screen); revokeTrust();
        thread.quitSafely(); super.onDestroy();
    }
}
