// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.facelab;

import android.content.Context;
import android.graphics.ImageFormat;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.util.Size;
import java.io.File;

/** Model blank inference and public front-camera metadata, without opening any camera. */
public final class NativeEngineSelfTest {
    public static void run(Context context) throws Exception {
        boolean front = false;
        CameraManager manager = context.getSystemService(CameraManager.class);
        for (String id : manager.getCameraIdList()) {
            CameraCharacteristics c = manager.getCameraCharacteristics(id);
            int[] caps = c.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES);
            boolean internal = false;
            if (caps != null) for (int cap : caps) if (cap == CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES_SYSTEM_CAMERA) internal = true;
            if (internal || !Integer.valueOf(CameraCharacteristics.LENS_FACING_FRONT).equals(c.get(CameraCharacteristics.LENS_FACING))) continue;
            StreamConfigurationMap streams = c.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
            if (streams == null) continue;
            Size[] sizes = streams.getOutputSizes(ImageFormat.YUV_420_888);
            if (sizes != null) for (Size size : sizes) if (size.equals(new Size(1280,960))) front = true;
        }
        if (!front) throw new IllegalStateException("Public front YUV1280x960 is unavailable");
        OpenCvEngine engine = new OpenCvEngine(context,new File("/data/system_de/0/sheng_face/models"));
        engine.checkFeatureOutput(); System.out.println(engine.benchmark());
        System.out.println("Pinned models/JNI and public front-camera metadata passed; camera not opened");
    }
}
