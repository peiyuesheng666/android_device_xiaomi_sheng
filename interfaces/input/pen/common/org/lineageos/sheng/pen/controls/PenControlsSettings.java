// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.pen.controls;

import android.content.Context;
import android.provider.Settings;

/** Android stores these preferences separately for each tablet user. */
public final class PenControlsSettings {
    private PenControlsSettings() {}
    public static String read(Context context, String key, int user) {
        return Settings.Secure.getStringForUser(context.getContentResolver(), key, user);
    }
    public static PenControls.Action action(Context context, PenControls.Gesture gesture, int user) {
        return PenControls.Action.read(read(context, gesture.key(), user), gesture.fallback);
    }
    public static int sensitivity(Context context, int user) {
        // Keep the OEM P81C initialization default; no user-adjustable strength.
        return 2;
    }
    public static int vibration(Context context, int user) {
        return 3;
    }
    public static boolean write(Context context, String key, String value) {
        boolean allowed = key.equals(PenControls.MENU);
        for (PenControls.Gesture gesture : PenControls.Gesture.values()) allowed |= key.equals(gesture.key());
        if (!allowed) throw new IllegalArgumentException("Unknown pen preference");
        return Settings.Secure.putString(context.getContentResolver(), key, value);
    }
}
