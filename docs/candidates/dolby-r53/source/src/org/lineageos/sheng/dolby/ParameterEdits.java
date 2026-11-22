// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.dolby;

import java.util.HashMap;

/** Retains the latest requested vector until confirmation, independently of UI refresh. */
final class ParameterEdits {
    static final class Edit {
        final int profile, parameter;
        private final int[] values;
        Edit(int profile, int parameter, int[] values) {
            this.profile = profile; this.parameter = parameter; this.values = values.clone();
        }
        int[] values() { return values.clone(); }
    }
    private final HashMap<String, Edit> latest = new HashMap<>();
    private final HashMap<String, int[]> desired = new HashMap<>();
    private long epoch;
    private String key(int profile, int parameter) { return profile + ":" + parameter; }
    synchronized Edit submit(int profile, int parameter, int[] values) {
        Edit edit = new Edit(profile, parameter, values);
        latest.put(key(profile, parameter), edit);
        desired.put(key(profile, parameter), edit.values());
        return edit;
    }
    synchronized Edit band(int profile, int parameter, int[] baseline, int band, int gain) {
        if (baseline.length != 20 || band < 0 || band >= 5 || gain < -384 || gain > 384)
            throw new IllegalArgumentException("Invalid grouped EQ edit");
        int[] previous = desired.get(key(profile, parameter));
        int[] values = previous == null ? baseline.clone() : previous.clone();
        for (int n = band * 4; n < band * 4 + 4; n++) values[n] = gain;
        return submit(profile, parameter, values);
    }
    synchronized boolean current(Edit edit) {
        return latest.get(key(edit.profile, edit.parameter)) == edit;
    }
    synchronized boolean confirm(Edit edit, Runnable save) {
        if (!current(edit)) return false;
        save.run();
        latest.remove(key(edit.profile, edit.parameter));
        return true;
    }
    synchronized void discard(Edit edit) {
        if (!current(edit)) return;
        latest.remove(key(edit.profile, edit.parameter));
        desired.remove(key(edit.profile, edit.parameter));
    }
    synchronized int[] pendingValues(int profile, int parameter) {
        Edit edit = latest.get(key(profile, parameter));
        return edit == null ? null : edit.values();
    }
    synchronized long invalidate() { latest.clear(); desired.clear(); return ++epoch; }
    synchronized long resetGains(int profile, int parameter) {
        invalidate();
        // A fresh drag may arrive before the reset's delayed UI refresh.
        desired.put(key(profile, parameter), new int[20]);
        return epoch;
    }
    synchronized long epoch() { return epoch; }
}
