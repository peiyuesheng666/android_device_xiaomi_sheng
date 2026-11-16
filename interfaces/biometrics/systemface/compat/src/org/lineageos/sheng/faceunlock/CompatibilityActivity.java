// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.faceunlock;

import android.app.Activity;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.widget.TextView;

/** API 1 entry shared by the modern system package and the nonfunctional legacy variant. */
public final class CompatibilityActivity extends Activity {
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        int api;
        try { api = Integer.parseInt(Build.VERSION.SDK); }
        catch (NumberFormatException invalid) { api = 1; }
        if (api >= 30) {
            try {
                Class<?> modern = Class.forName("org.lineageos.sheng.facelab.FaceUnlockActivity");
                if (Boolean.TRUE.equals(modern.getMethod("supported", new Class[0]).invoke(null, new Object[0]))) {
                Intent page = new Intent(); page.setClassName(this, "org.lineageos.sheng.facelab.FaceUnlockActivity");
                startActivity(page); finish(); return;
                }
            } catch (Exception unavailable) {
                // The legacy variant intentionally excludes the modern feature classes.
            } catch (LinkageError unavailable) {
                // A missing platform feature must leave the compatibility entry usable.
            }
        }
        setTitle("FaceUnlock");
        TextView explanation = new TextView(this); explanation.setTextSize(18);
        explanation.setPadding(24,24,24,24);
        explanation.setText("此系统版本不支持人脸解锁。请继续使用锁屏密码或指纹。\n"
                + "Face unlock is unavailable on this system. Use your device credential or fingerprint.");
        setContentView(explanation);
    }
}
