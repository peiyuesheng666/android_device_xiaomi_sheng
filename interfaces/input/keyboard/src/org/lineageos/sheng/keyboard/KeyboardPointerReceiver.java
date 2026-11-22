// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.keyboard;

import android.Manifest;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.Handler;
import android.provider.Settings;
import android.util.Log;

/** Narrow system-setting broker; never accepts arbitrary setting names or users. */
final class KeyboardPointerReceiver extends BroadcastReceiver {
    static final String ACTION = "org.lineageos.sheng.keyboard.SET_POINTER";

    static void register(Context context, Handler handler) {
        context.registerReceiver(new KeyboardPointerReceiver(), new IntentFilter(ACTION),
                Manifest.permission.WRITE_SECURE_SETTINGS, handler, Context.RECEIVER_EXPORTED);
    }

    @Override public void onReceive(Context context, Intent intent) {
        if (!ACTION.equals(intent.getAction())) return;
        int value = intent.getIntExtra("value", Integer.MIN_VALUE);
        String setting;
        if ("speed".equals(intent.getStringExtra("control")) && value >= -7 && value <= 7) {
            setting = Settings.System.TOUCHPAD_POINTER_SPEED;
        } else if ("natural".equals(intent.getStringExtra("control")) && (value == 0 || value == 1)) {
            setting = Settings.System.TOUCHPAD_NATURAL_SCROLLING;
        } else return;
        try {
            boolean written = Settings.System.putInt(context.getContentResolver(), setting, value);
            Log.i("ShengKeyboard", "Pointer " + intent.getStringExtra("control")
                    + " value=" + value + " written=" + written);
        } catch (SecurityException | IllegalArgumentException failure) {
            Log.w("ShengKeyboard", "Pointer setting rejected", failure);
        }
    }
}
