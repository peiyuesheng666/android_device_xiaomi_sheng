// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.face;

/** Twelve valid, spaced samples, optionally spanning center/left/right head poses. */
public final class EnrollmentPoseGate {
    public static final long INTERVAL_NS = 250_000_000L;
    private final boolean diverse;
    private int count;
    private double baseline;
    private long last = -1;
    public EnrollmentPoseGate(boolean diverse) { this.diverse = diverse; }
    public int count() { return count; }
    /** 0=center, -1=left, +1=right; capture sends the native guidance callback. */
    public int direction() { return !diverse || count < 4 ? 0 : count < 8 ? -1 : 1; }
    public boolean offer(long timestamp, float pan, float tilt) {
        if (count >= 12 || timestamp < 0 || (last >= 0 && timestamp - last < INTERVAL_NS)
                || !Float.isFinite(pan) || !Float.isFinite(tilt) || Math.abs(tilt) > .30) return false;
        int direction = direction();
        if (direction == 0 && Math.abs(pan) > .15) return false;
        if (direction != 0) {
            double delta = pan - baseline / 4;
            if (Math.abs(delta) > .45 || (direction < 0 ? delta > -.10 : delta < .10)) return false;
        }
        if (diverse && count < 4) baseline += pan;
        count++; last = timestamp; return true;
    }
}
