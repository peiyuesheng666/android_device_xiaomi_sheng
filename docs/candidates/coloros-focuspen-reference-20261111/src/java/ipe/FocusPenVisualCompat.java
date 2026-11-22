package com.codex.focuspen.ipe;

import android.util.Log;
import android.os.SystemClock;
import java.lang.reflect.Method;
import org.json.JSONObject;

/** Visual-only adapter called inside IPeManager; Bluetooth identity stays unchanged. */
public final class FocusPenVisualCompat {
    private FocusPenVisualCompat() { }
    private static long lastExpandedAt = -30000;

    public static void apply(JSONObject data, String name, Object options, int cardType) {
        if (data == null) return;
        try {
            boolean focusPen = "Xiaomi Focus Pen".equals(name) || "Xiaomi Focus Pen Pro".equals(name);
            data.put("show_focuspen_animation", focusPen);
            if (focusPen) {
                data.put("focuspen_animation", "/assets/images/focuspen_connected.json");
                long now = SystemClock.elapsedRealtime();
                if (options != null && cardType == 18 && now - lastExpandedAt >= 30000) {
                    Method expand = options.getClass().getMethod("setRequestShowPanel", Boolean.class);
                    expand.invoke(options, Boolean.TRUE);
                    lastExpandedAt = now;
                }
                Log.i("FocusPenVisualCompat", "Native card animation enabled for " + name);
            }
        } catch (Exception e) {
            Log.e("FocusPenVisualCompat", "Card visual adapter failed", e);
        }
    }
}
