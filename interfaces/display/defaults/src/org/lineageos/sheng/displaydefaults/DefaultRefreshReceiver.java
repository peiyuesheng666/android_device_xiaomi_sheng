// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.displaydefaults;

import android.content.BroadcastReceiver;
import android.content.ContentResolver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.hardware.display.DisplayManager;
import android.os.Build;
import android.provider.Settings;
import android.util.Log;
import android.view.Display;

/** Seeds a new user's display settings once, before setup is completed. */
public final class DefaultRefreshReceiver extends BroadcastReceiver {
    private static final String TAG = "ShengDisplayDefaults";
    // These platform setting names are stable, but their constants are hidden
    // from the public SDK. Use the public Settings provider API directly.
    private static final String PEAK = "peak_refresh_rate", MIN = "min_refresh_rate";
    private static final String INITIALIZED = "refresh_defaults_initialized";

    @Override public void onReceive(Context context, Intent intent) {
        String action = intent.getAction();
        if (!Intent.ACTION_LOCKED_BOOT_COMPLETED.equals(action)
                && !Intent.ACTION_BOOT_COMPLETED.equals(action)
                && !Intent.ACTION_USER_INITIALIZE.equals(action)) return;
        if (!"sheng".equals(Build.DEVICE)) return;
        Display display = context.getSystemService(DisplayManager.class).getDisplay(Display.DEFAULT_DISPLAY);
        if (display == null) return;
        boolean supported = false;
        for (Display.Mode mode : display.getSupportedModes())
            if (Math.abs(mode.getRefreshRate() - 144f) < .5f) supported = true;
        if (!supported) { Log.w(TAG,"144 Hz is not advertised; defaults unchanged"); return; }
        ContentResolver resolver = context.getContentResolver();
        try {
            SharedPreferences state = context.createDeviceProtectedStorageContext()
                    .getSharedPreferences("display_defaults", Context.MODE_PRIVATE);
            // A completed user may receive this package through an OTA. Do not
            // mistake the absence of this new marker for a fresh installation.
            boolean firstSetup = !state.getBoolean(INITIALIZED, false)
                    && Settings.Secure.getInt(resolver, "user_setup_complete", 0) == 0;
            initialize(resolver, PEAK, firstSetup);
            initialize(resolver, MIN, firstSetup);
            if (!state.getBoolean(INITIALIZED, false) && !state.edit()
                    .putBoolean(INITIALIZED, true).commit())
                throw new IllegalStateException("Could not persist initialization marker");
        } catch (RuntimeException failure) {
            Log.e(TAG,"Could not initialize display defaults",failure);
        }
    }

    private static void initialize(ContentResolver resolver, String key, boolean firstSetup) {
        // Setup/restored provider rows can already contain 60 Hz. Only this
        // user's first setup initialization may replace an existing value.
        if (!firstSetup && Settings.System.getString(resolver,key) != null) return;
        if (!Settings.System.putFloat(resolver,key,144f))
            throw new IllegalStateException("Settings write failed: " + key);
        Log.i(TAG,"Initialized " + key + " to 144 Hz");
    }
}
