// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.face;

import android.app.ActivityThread;
import android.content.Context;
import android.os.Looper;
import android.os.Process;

/** Init-owned Java HAL. The package's normal classloader owns JNI and model assets. */
public final class NativeFaceMain {
    public static void main(String[] args) throws Exception {
        if (Process.myUid() != Process.SYSTEM_UID) throw new SecurityException("System UID required");
        Looper.prepareMainLooper();
        Context system = ActivityThread.systemMain().getSystemContext();
        // This init process does not go through ActivityThread.handleBindApplication.
        // Install the platform's JCA providers before using hardware-backed storage.
        android.security.keystore2.AndroidKeyStoreProvider.install();
        Context payload = system.createPackageContext("org.lineageos.sheng.faceunlock",
                Context.CONTEXT_INCLUDE_CODE | Context.CONTEXT_IGNORE_SECURITY);
        if (payload.getApplicationInfo().uid != Process.SYSTEM_UID) throw new SecurityException("Unexpected payload UID");
        Class<?> runtime = payload.getClassLoader().loadClass("org.lineageos.sheng.face.NativeFaceRuntime");
        boolean test = args.length == 1 && "--self-test".equals(args[0]);
        if (args.length != 0 && !test) throw new IllegalArgumentException("Unknown startup mode");
        runtime.getMethod(test ? "selfTest" : "start", Context.class).invoke(null, payload);
        if (!test) Looper.loop();
    }
}
