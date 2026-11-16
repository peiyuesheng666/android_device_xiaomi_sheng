// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.pen;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.widget.TextView;

/** API 1 Settings entry. Modern Bluetooth classes are loaded only after the API check. */
public final class CompatibilityActivity extends Activity {
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        int api;
        try { api = Integer.parseInt(Build.VERSION.SDK); }
        catch (NumberFormatException invalid) { api = 1; }
        if (api >= 35) {
            try {
                Class modern = Class.forName("org.lineageos.sheng.pen.PenSettingsActivity");
                Object supported = modern.getMethod("supported", new Class[]{Context.class})
                        .invoke(null, new Object[]{this});
                if (Boolean.TRUE.equals(supported)) {
                    Intent page = new Intent();
                    page.setClassName(this, "org.lineageos.sheng.pen.PenSettingsActivity");
                    startActivity(page);finish();return;
                }
            } catch (Exception unavailable) {
                // Keep the Settings entry usable if the platform lacks this feature.
            } catch (LinkageError unavailable) {
                // Old platforms must not resolve modern Bluetooth APIs.
            }
        }
        setTitle(R.string.app_name);
        TextView explanation = new TextView(this);
        explanation.setText(R.string.unsupported_platform);
        explanation.setTextSize(18);
        explanation.setPadding(24,24,24,24);
        setContentView(explanation);
    }
}
