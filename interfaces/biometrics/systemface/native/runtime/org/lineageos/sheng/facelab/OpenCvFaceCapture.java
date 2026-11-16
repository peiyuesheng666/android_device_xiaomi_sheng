// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.facelab;

import android.Manifest;
import android.app.AppOpsManager;
import android.app.KeyguardManager;
import android.app.admin.DevicePolicyManager;
import android.content.Context;
import android.content.pm.PackageManager;
import android.graphics.ImageFormat;
import android.hardware.SensorPrivacyManager;
import android.hardware.biometrics.face.AcquiredInfo;
import android.hardware.biometrics.face.EnrollmentStage;
import android.hardware.biometrics.face.Error;
import android.hardware.camera2.*;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.hardware.camera2.params.OutputConfiguration;
import android.hardware.display.DisplayManager;
import android.media.Image;
import android.media.ImageReader;
import android.os.Handler;
import android.os.UserHandle;
import android.os.UserManager;
import android.util.Range;
import android.util.Size;
import android.view.Surface;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;
import org.lineageos.sheng.face.EnrollmentPoseGate;
import org.lineageos.sheng.face.FaceCapture;

/** Real Camera2 driver for native Face enrollment/authentication; no image storage. */
public final class OpenCvFaceCapture implements FaceCapture {
    private final Context context;
    private final int user;
    private final Handler cameraWorker, analysis;
    private final AtomicLong generation = new AtomicLong();
    private CameraDevice camera;
    private CameraCaptureSession session;
    private ImageReader reader;
    // All sessions use the runtime's single analysis worker. Keep only models
    // across sessions; frames and embeddings remain operation-owned and wiped.
    private static OpenCvEngine engine;
    private volatile boolean active, analyzing;
    private volatile boolean enrollmentActive;
    private long lastAnalyzed;
    private int rotation, displayRotation;
    private String lastPolicyBlock;

    public OpenCvFaceCapture(Context context, int user, Handler cameraWorker, Handler analysis) {
        this.context = context; this.user = user; this.cameraWorker = cameraWorker; this.analysis = analysis;
    }
    @Override public boolean supportsDiversePoses() { return true; }
    private boolean permitted() {
        String block = policyBlock(context, user, enrollmentActive);
        if (block != null && !block.equals(lastPolicyBlock))
            android.util.Log.w("ShengNativeFace", "Capture policy blocked: " + block);
        lastPolicyBlock = block;
        return block == null;
    }
    /** Read-only environment diagnosis; this method never opens a camera. */
    public static void checkEnrollmentPolicy(Context context) {
        String block = policyBlock(context, 0, true);
        android.util.Log.i("ShengNativeFace", "Enrollment policy preflight: " + (block == null ? "allowed" : block));
    }
    private static String policyBlock(Context context, int user, boolean enrolling) {
        String service = "user";
        try {
            if (!context.getSystemService(UserManager.class).isUserUnlocked(UserHandle.of(user))) return "user-locked";
            service = "keyguard";
            if (!context.getSystemService(KeyguardManager.class).isDeviceSecure(user)) return "credential-required";
            service = "permission";
            if (context.checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) return "camera-permission";
            service = "power";
            if (!context.getSystemService(android.os.PowerManager.class).isInteractive()) return "screen-off";
            service = "sensor-privacy";
            SensorPrivacyManager privacy = context.getSystemService(SensorPrivacyManager.class);
            if (privacy.isSensorPrivacyEnabled(SensorPrivacyManager.TOGGLE_TYPE_SOFTWARE, SensorPrivacyManager.Sensors.CAMERA)
                    || privacy.isSensorPrivacyEnabled(SensorPrivacyManager.TOGGLE_TYPE_HARDWARE, SensorPrivacyManager.Sensors.CAMERA)) return "camera-privacy";
            service = "appops";
            int mode = context.getSystemService(AppOpsManager.class).checkOpNoThrow(
                    AppOpsManager.OPSTR_CAMERA, android.os.Process.myUid(), context.getOpPackageName());
            if (mode != AppOpsManager.MODE_ALLOWED && mode != AppOpsManager.MODE_FOREGROUND) return "camera-appop-" + mode;
            service = "device-policy";
            int policy = context.getSystemService(DevicePolicyManager.class).getKeyguardDisabledFeatures(null, user);
            service = "strong-auth";
            if (!enrolling && new com.android.internal.widget.LockPatternUtils(context).getStrongAuthForUser(user) != 0) return "strong-auth-required";
            return (policy & (DevicePolicyManager.KEYGUARD_DISABLE_FACE | DevicePolicyManager.KEYGUARD_DISABLE_BIOMETRICS)) == 0 ? null : "device-policy";
        } catch (RuntimeException failure) { return "service-" + service + "-" + failure.getClass().getSimpleName(); }
    }
    private boolean current(long token) { return active && generation.get() == token && permitted(); }
    @Override public void start(boolean enrolling, Surface preview, boolean diverse, Listener listener) {
        stop();
        enrollmentActive = enrolling;
        if (!permitted() || (enrolling && (preview == null || !preview.isValid()))) {
            listener.error(Error.HW_UNAVAILABLE); return;
        }
        long token = generation.incrementAndGet(); active = true;
        EnrollmentPoseGate poses = new EnrollmentPoseGate(diverse);
        // The model/classloader uses the pinned APK payload, never an external model.
        analysis.post(() -> {
            try {
                if (!current(token)) return;
                if (engine == null) engine = new OpenCvEngine(context,
                        new java.io.File("/data/system_de/0/sheng_face/models"));
                android.util.Log.i("ShengNativeFace", "Capture models ready");
                if (current(token)) cameraWorker.post(() -> open(token, enrolling, preview, poses, listener));
            } catch (Exception | LinkageError failure) {
                android.util.Log.e("ShengNativeFace", "Capture model initialization: " + failure.getClass().getSimpleName());
                error(token, listener, Error.HW_UNAVAILABLE);
            }
        });
        cameraWorker.postDelayed(new Runnable() {
            @Override public void run() {
                if (!active || generation.get() != token) return;
                if (!permitted()) { error(token,listener,Error.CANCELED); return; }
                cameraWorker.postDelayed(this,250);
            }
        },250);
    }
    private void error(long token, Listener listener, byte error) {
        if (generation.get() != token || !active) return;
        stop(); listener.error(error);
    }
    @Override public void stop() {
        active = false; generation.incrementAndGet();
        cameraWorker.post(this::closeCamera);
    }
    private void closeCamera() {
        if (session != null) { try { session.close(); } catch (RuntimeException ignored) {} finally { session = null; } }
        if (camera != null) { try { camera.close(); } catch (RuntimeException ignored) {} finally { camera = null; } }
        if (reader != null) { try { reader.close(); } catch (RuntimeException ignored) {} finally { reader = null; } }
        lastAnalyzed = 0;
    }
    private void open(long token, boolean enrolling, Surface preview, EnrollmentPoseGate poses, Listener listener) {
        if (!current(token)) return;
        android.util.Log.i("ShengNativeFace", "Opening public front camera for requested operation");
        try {
            CameraManager manager = context.getSystemService(CameraManager.class);
            String front = null; CameraCharacteristics chars = null;
            for (String id : manager.getCameraIdList()) {
                CameraCharacteristics c = manager.getCameraCharacteristics(id);
                int[] caps = c.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES);
                boolean internal = false;
                if (caps != null) for (int cap : caps) if (cap == CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_SYSTEM_CAMERA) internal = true;
                if (internal || !Integer.valueOf(CameraCharacteristics.LENS_FACING_FRONT).equals(c.get(CameraCharacteristics.LENS_FACING))) continue;
                StreamConfigurationMap streams = c.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
                if (streams == null) continue;
                boolean resolution = false;
                Size[] sizes = streams.getOutputSizes(ImageFormat.YUV_420_888);
                if (sizes != null) for (Size size : sizes) if (size.equals(new Size(1280,960))) resolution = true;
                if (resolution) { front = id; chars = c; break; }
            }
            if (front == null || chars == null) { error(token, listener, Error.HW_UNAVAILABLE); return; }
            Integer orientation = chars.get(CameraCharacteristics.SENSOR_ORIENTATION);
            if (orientation == null) throw new IllegalStateException("Missing sensor orientation");
            displayRotation = context.getSystemService(DisplayManager.class).getDisplay(0).getRotation();
            rotation = FrameMath.rotation(orientation, displayRotation * 90);
            reader = ImageReader.newInstance(1280,960,ImageFormat.YUV_420_888,3);
            reader.setOnImageAvailableListener(input -> image(input, token, enrolling, poses, listener), cameraWorker);
            final CameraCharacteristics selected = chars;
            manager.openCamera(front, new CameraDevice.StateCallback() {
                @Override public void onOpened(CameraDevice device) {
                    if (!current(token)) { device.close(); return; }
                    camera = device;
                    try {
                        Surface yuv = reader.getSurface();
                        List<Surface> outputs = enrolling ? Arrays.asList(yuv,preview) : Collections.singletonList(yuv);
                        OutputConfiguration yuvConfig = new OutputConfiguration(yuv);
                        yuvConfig.setMirrorMode(OutputConfiguration.MIRROR_MODE_NONE);
                        List<OutputConfiguration> configs = new ArrayList<>(); configs.add(yuvConfig);
                        if (enrolling) {
                            // Camera2 rotation is counterclockwise; FrameMath's sampler is clockwise.
                            OutputConfiguration previewConfig = new OutputConfiguration(preview,(360-rotation)%360/90);
                            previewConfig.setMirrorMode(OutputConfiguration.MIRROR_MODE_H);
                            configs.add(previewConfig);
                        }
                        device.createCaptureSessionByOutputConfigurations(configs, new CameraCaptureSession.StateCallback() {
                            @Override public void onConfigured(CameraCaptureSession configured) {
                                if (!current(token)) { configured.close(); return; }
                                session = configured;
                                try {
                                    CaptureRequest.Builder request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
                                    for (Surface output : outputs) request.addTarget(output);
                                    request.set(CaptureRequest.CONTROL_MODE,CaptureRequest.CONTROL_MODE_AUTO);
                                    request.set(CaptureRequest.STATISTICS_FACE_DETECT_MODE,CaptureRequest.STATISTICS_FACE_DETECT_MODE_OFF);
                                    int[] rotateModes = selected.get(CameraCharacteristics.SCALER_AVAILABLE_ROTATE_AND_CROP_MODES);
                                    if (rotateModes != null) for (int mode : rotateModes) if (mode == CaptureRequest.SCALER_ROTATE_AND_CROP_NONE) {
                                        request.set(CaptureRequest.SCALER_ROTATE_AND_CROP,mode); break;
                                    }
                                    Range<Integer>[] fps = selected.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES);
                                    if (fps != null) for (Range<Integer> range : fps) if (range.equals(new Range<>(30,30))) {
                                        request.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE,range); break;
                                    }
                                    configured.setRepeatingRequest(request.build(),null,cameraWorker);
                                } catch (Exception failure) {
                                    diagnostic("repeating-request",failure); error(token,listener,Error.HW_UNAVAILABLE);
                                }
                            }
                            @Override public void onConfigureFailed(CameraCaptureSession configured) {
                                android.util.Log.e("ShengNativeFace", "Camera stream configuration rejected");
                                configured.close(); error(token,listener,Error.HW_UNAVAILABLE);
                            }
                        },cameraWorker);
                    } catch (Exception failure) { diagnostic("stream-setup",failure); error(token,listener,Error.HW_UNAVAILABLE); }
                }
                @Override public void onDisconnected(CameraDevice device) { device.close(); error(token,listener,Error.HW_UNAVAILABLE); }
                @Override public void onError(CameraDevice device, int error) {
                    android.util.Log.e("ShengNativeFace", "Camera device error=" + error);
                    device.close(); error(token,listener,Error.HW_UNAVAILABLE);
                }
            },cameraWorker);
        } catch (Exception | LinkageError failure) { diagnostic("camera-open",failure); error(token,listener,Error.HW_UNAVAILABLE); }
    }
    private static void diagnostic(String phase, Throwable failure) {
        android.util.Log.e("ShengNativeFace", "Capture failed at " + phase + ": " + failure.getClass().getSimpleName());
    }
    private void image(ImageReader input, long token, boolean enrolling, EnrollmentPoseGate poses, Listener listener) {
        OpenCvEngine.Frame frame = null; long timestamp;
        try (Image image = input.acquireLatestImage()) {
            if (image == null) return;
            if (!current(token) || context.getSystemService(DisplayManager.class).getDisplay(0).getRotation() != displayRotation) {
                error(token,listener,Error.CANCELED); return;
            }
            if (analyzing || image.getTimestamp() - lastAnalyzed < 100_000_000L) return;
            timestamp = image.getTimestamp(); lastAnalyzed = timestamp;
            frame = OpenCvEngine.capture(image); analyzing = true;
        } catch (Exception failure) { diagnostic("image-acquisition",failure); error(token,listener,Error.HW_UNAVAILABLE); return; }
        final OpenCvEngine.Frame owned = frame;
        analysis.post(() -> {
            OpenCvEngine.Result result = null;
            try {
                if (!current(token)) return;
                result = engine.analyze(owned,rotation,true,enrolling);
                if (!current(token)) return;
                float[] embedding = result.embedding;
                byte acquired = embedding != null ? AcquiredInfo.GOOD
                        : result.face == null ? AcquiredInfo.NOT_DETECTED : AcquiredInfo.TOO_FAR;
                byte stage = EnrollmentStage.HOLD_STILL_IN_CENTER;
                int vendorCode = 0;
                if (enrolling) {
                    int direction = poses.direction();
                    stage = direction == 0 ? EnrollmentStage.HOLD_STILL_IN_CENTER
                            : direction < 0 ? EnrollmentStage.ENROLLING_MOVEMENT_1 : EnrollmentStage.ENROLLING_MOVEMENT_2;
                    if (embedding == null) { acquired = AcquiredInfo.VENDOR; vendorCode = 0; }
                    else if (!poses.offer(timestamp,result.pan,result.tilt)) {
                        embedding = null; acquired = AcquiredInfo.VENDOR;
                        vendorCode = direction < 0 ? 1 : direction > 0 ? 2 : 0;
                    }
                }
                listener.frame(timestamp,embedding,acquired,vendorCode,stage,result.pan,result.tilt);
            } catch (Exception | LinkageError failure) { diagnostic("inference",failure); error(token,listener,Error.UNABLE_TO_PROCESS); }
            finally {
                if (owned != null) owned.clear();
                if (result != null && result.embedding != null) Arrays.fill(result.embedding,0);
                analyzing = false;
            }
        });
    }
}
