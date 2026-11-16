// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.facelab;

import android.content.ComponentName;
import android.content.Context;
import android.os.UserHandle;
import android.os.PowerManager;
import android.provider.Settings;
import com.android.internal.widget.LockPatternUtils;
import java.util.ArrayList;
import java.util.List;

final class FaceUnlockSettings {
    static final String PREFS = "face-unlock", ENABLED = "enabled";
    private static final boolean SUPPORTED = supportsRenewableTrust();
    static boolean supported() { return SUPPORTED; }
    private static boolean supportsRenewableTrust() {
        try {
            Class<?> trust = android.service.trust.TrustAgentService.class;
            if (trust.getField("FLAG_GRANT_TRUST_TEMPORARY_AND_RENEWABLE").getInt(null)
                    != android.service.trust.TrustAgentService.FLAG_GRANT_TRUST_TEMPORARY_AND_RENEWABLE) return false;
            trust.getMethod("onUserRequestedUnlock", boolean.class);
            return true;
        } catch (ReflectiveOperationException | LinkageError unavailable) { return false; }
    }
    static ComponentName agent(Context context) { return new ComponentName(context, FaceUnlockService.class); }
    static boolean enabled(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(ENABLED, false);
    }
    static void enabled(Context context, boolean value) {
        android.content.SharedPreferences preferences = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        boolean wasEnabled = preferences.getBoolean(ENABLED, false);
        LockPatternUtils lock = new LockPatternUtils(context);
        int user = UserHandle.myUserId();
        List<ComponentName> old = lock.getEnabledTrustAgents(user);
        List<ComponentName> agents = old == null ? new ArrayList<>() : new ArrayList<>(old);
        ComponentName component = agent(context);
        agents.remove(component);
        if (value) agents.add(component);
        android.content.SharedPreferences.Editor edit = preferences.edit().putBoolean(ENABLED, value);
        String[] keys = {"active_unlock_on_wake", "active_unlock_on_unlock_intent",
                "active_unlock_wakeups_to_force_dismiss_keyguard"};
        String priorWakeups = Settings.Secure.getString(context.getContentResolver(), keys[2]);
        String wakeups = priorWakeups == null ? Integer.toString(PowerManager.WAKE_REASON_UNFOLD_DEVICE) : priorWakeups;
        for (int reason : new int[]{PowerManager.WAKE_REASON_POWER_BUTTON, PowerManager.WAKE_REASON_GESTURE,
                PowerManager.WAKE_REASON_WAKE_KEY, PowerManager.WAKE_REASON_TAP}) {
            String code = Integer.toString(reason);
            boolean exists = false;
            for (String existing : wakeups.split("\\|")) if (code.equals(existing)) exists = true;
            if (!exists) wakeups += (wakeups.isEmpty() ? "" : "|") + code;
        }
        String[] written = {"1", "1", wakeups};
        if (value && !wasEnabled) for (String key : keys)
            edit.putString("previous_" + key, Settings.Secure.getString(context.getContentResolver(), key));
        if (value) for (int i = 0; i < keys.length; i++) edit.putString("written_" + keys[i], written[i]);
        // Update consent before the platform binds (or unbinds) the agent.
        if (!edit.commit()) throw new IllegalStateException("Consent write failed");
        try {
            if (value) for (int i = 0; i < keys.length; i++) {
                if (!Settings.Secure.putString(context.getContentResolver(), keys[i], written[i]))
                    throw new IllegalStateException("Active unlock configuration failed");
            }
            lock.setEnabledTrustAgents(agents, user);
        } catch (RuntimeException failure) {
            preferences.edit().putBoolean(ENABLED, false).commit();
            agents.remove(component); lock.setEnabledTrustAgents(agents, user);
            restore(context, preferences, keys); throw failure;
        }
        if (!value && wasEnabled) restore(context, preferences, keys);
    }
    private static void restore(Context context, android.content.SharedPreferences preferences, String[] keys) {
        for (String key : keys) if (preferences.getString("written_" + key, "1")
                .equals(Settings.Secure.getString(context.getContentResolver(), key)))
            Settings.Secure.putString(context.getContentResolver(), key, preferences.getString("previous_" + key, null));
    }
}
