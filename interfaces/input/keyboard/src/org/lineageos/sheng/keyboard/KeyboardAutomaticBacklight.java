// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.keyboard;

import android.content.Context;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.os.Handler;
import android.provider.Settings;

/** Read-only ambient sensing; never writes sensor or persist calibration data. */
final class KeyboardAutomaticBacklight implements SensorEventListener {
    private static final String AUTO = "sheng_keyboard_backlight_auto";
    private static final String EFFECTIVE = "sheng_keyboard_backlight_effective_percent";
    private final Context context;
    private final Handler worker;
    private final SensorManager sensors;
    private final Sensor light;
    private boolean listening;
    private float filtered = -1;
    private int percent = -1;

    KeyboardAutomaticBacklight(Context context, Handler worker) {
        this.context = context; this.worker = worker;
        sensors = context.getSystemService(SensorManager.class);
        light = sensors == null ? null : sensors.getDefaultSensor(Sensor.TYPE_LIGHT);
    }

    boolean enabled() {
        return Settings.Secure.getInt(context.getContentResolver(), AUTO, 0) != 0;
    }

    // Last brightness submitted to the HAL, not a claimed hardware ACK.
    void submitted(int value) {
        if (Settings.Secure.getInt(context.getContentResolver(), EFFECTIVE, -1) == value) return;
        try {
            if (!Settings.Secure.putInt(context.getContentResolver(), EFFECTIVE, value)) {
                android.util.Log.w("ShengKeyboard", "Cannot publish backlight level");
            }
        } catch (SecurityException denied) {
            android.util.Log.w("ShengKeyboard", "Cannot publish backlight level");
        }
    }

    int resolve(boolean usable, int manual) {
        boolean wanted = usable && light != null && enabled();
        if (wanted && !listening) {
            filtered = -1; percent = -1;
            listening = sensors.registerListener(this, light, SensorManager.SENSOR_DELAY_NORMAL, worker);
        } else if (!wanted && listening) {
            sensors.unregisterListener(this); listening = false;
            filtered = -1; percent = -1;
        }
        return wanted && listening && percent >= 0 ? percent : manual;
    }

    @Override public void onSensorChanged(SensorEvent event) {
        if (!listening || event.values.length == 0 || KeyboardLightCurve.percent(event.values[0]) < 0) return;
        filtered = filtered < 0 ? event.values[0] : filtered * .8f + event.values[0] * .2f;
        int next = KeyboardLightCurve.percent(filtered);
        // A 10 percentage-point deadband avoids repeated small brightness commands.
        if (percent < 0 || Math.abs(next - percent) >= 10) percent = next;
    }
    @Override public void onAccuracyChanged(Sensor sensor, int accuracy) {}
}
