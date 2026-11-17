// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

import org.lineageos.sheng.pen.controls.PenControls.Gesture;

/** Decode only the one-byte keyboard input report, never the pressure report. */
public final class PenButtonState {
    public interface Listener {
        void down(Gesture gesture);
        void up(Gesture gesture);
    }
    public static final long HOLD_MS = 380;
    private final Listener listener;
    private int usage;
    private long since;
    private boolean longSent;
    private boolean sideButtonLongPress = true;
    public PenButtonState(Listener listener) { this.listener = listener; }

    public void setSideButtonLongPress(boolean enabled) {
        if (sideButtonLongPress == enabled) return;
        clear();
        sideButtonLongPress = enabled;
    }

    private boolean requiresHold(Gesture gesture) {
        return sideButtonLongPress && gesture.longPress();
    }

    public static Gesture gesture(int usage) {
        switch (usage) {
            case 0x4e: return Gesture.PRIMARY;
            case 0x4b: return Gesture.SECONDARY;
            case 0x6e: return Gesture.SQUEEZE;
            case 0x58: return Gesture.DOUBLE_TAP;
            case 0x61: return Gesture.SLIDE_UP;
            case 0x5b: return Gesture.SLIDE_DOWN;
            default: return null;
        }
    }

    public boolean accept(byte[] report, long now) {
        if (report == null || report.length != 1 || now < 0) { clear(); return false; }
        int next = report[0] & 255;
        if (next != 0 && gesture(next) == null) { clear(); return false; }
        if (next == usage) return true;
        Gesture old = gesture(usage);
        usage = next; since = now; longSent = false;
        if (old != null) listener.up(old);
        Gesture current = gesture(next);
        if (current != null && !requiresHold(current)) listener.down(current);
        return true;
    }

    public void held(long now) {
        Gesture current = gesture(usage);
        if (current != null && requiresHold(current) && !longSent && now >= since + HOLD_MS) {
            longSent = true; listener.down(current);
        }
    }
    public long holdDelay(long now) {
        Gesture current = gesture(usage);
        return current == null || !requiresHold(current) || longSent ? -1 : Math.max(0, since + HOLD_MS - now);
    }
    /** Cancellation is not a physical release and must not generate feedback/actions. */
    public void clear() { usage = 0; since = 0; longSent = false; }
}
