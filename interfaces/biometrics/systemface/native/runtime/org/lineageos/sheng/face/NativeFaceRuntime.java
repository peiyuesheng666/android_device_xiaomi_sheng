// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.face;

import android.content.Context;
import android.hardware.biometrics.face.IFace;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.ServiceManager;
import android.os.UserManager;
import android.util.Log;
import org.lineageos.sheng.facelab.OpenCvFaceCapture;
import org.lineageos.sheng.facelab.NativeEngineSelfTest;

/** Registers only the standard IFace/default binder; no application UI or trust agent. */
public final class NativeFaceRuntime {
    private static NativeFaceProvider provider;
    private static android.os.IBinder framework;
    public static synchronized void start(Context context) {
        if (provider != null) throw new IllegalStateException("Provider already running");
        try {
            // Context services cache system_server Binder proxies. Recreate this
            // process after framework death instead of retaining stale managers.
            framework = ServiceManager.getService("activity");
            if (framework == null) throw new IllegalStateException("Framework not ready");
            framework.linkToDeath(() -> android.os.Process.killProcess(android.os.Process.myPid()), 0);
        } catch (android.os.RemoteException gone) { throw new IllegalStateException("Framework died during startup", gone); }
        HandlerThread protocol = new HandlerThread("sheng-face-protocol"); protocol.start();
        HandlerThread cameras = new HandlerThread("sheng-face-camera"); cameras.start();
        HandlerThread analysis = new HandlerThread("sheng-face-analysis"); analysis.start();
        Handler worker = new Handler(protocol.getLooper()), camera = new Handler(cameras.getLooper()),
                engine = new Handler(analysis.getLooper());
        UserManager users = context.getSystemService(UserManager.class);
        provider = new NativeFaceProvider(worker, new NativeFaceProvider.Factory() {
            private void validUser(int user) {
                if (users.getUserInfo(user) == null) throw new IllegalArgumentException("Unknown Android user");
            }
            @Override public FaceRepository repository(int user) {
                validUser(user); return new EncryptedFaceRepository(user,users);
            }
            @Override public FaceCapture capture(int user) {
                validUser(user); return new OpenCvFaceCapture(context,user,camera,engine);
            }
        });
        String name = IFace.DESCRIPTOR + "/default";
        ServiceManager.addService(name,provider,false);
        if (ServiceManager.checkService(name) == null) throw new IllegalStateException("Native Face registration failed");
        Log.i("ShengNativeFace","IFace V5 provider registered; CONVENIENCE; no capture at startup");
    }
    public static void selfTest(Context context) throws Exception {
        // This entry never constructs/registers a provider or starts capture.
        android.os.SystemProperties.set("sys.sheng.face.test_result","running");
        try {
            OpenCvFaceCapture.checkEnrollmentPolicy(context);
            NativeStorageSelfTest.run(context);
            NativeEngineSelfTest.run(context);
            Log.i("ShengNativeFace","Native backend self-test passed; no service registered, no camera opened");
            android.os.SystemProperties.set("sys.sheng.face.test_result","passed");
        } catch (Exception | LinkageError | AssertionError failure) {
            Log.e("ShengNativeFace","Native backend self-test failed: " + failure.getClass().getSimpleName());
            android.os.SystemProperties.set("sys.sheng.face.test_result","failed");
            throw failure;
        } finally { android.os.SystemProperties.set("sys.sheng.face.test_request","0"); }
    }
}
