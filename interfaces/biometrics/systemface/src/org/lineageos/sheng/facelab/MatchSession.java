// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.facelab;

/** A bounded recognition attempt; a cancelled or expired attempt can never grant trust. */
public final class MatchSession {
    public static final double THRESHOLD = .5;
    public static final int REQUIRED = 3;
    public static final long TIMEOUT_MS = 5_000, INTERVAL_NS = 100_000_000L;
    private long generation, started, lastFrame;
    private int goodFrames;
    private boolean active;

    public synchronized long begin(long now) {
        if (now < 0) throw new IllegalArgumentException("Invalid monotonic time");
        generation++; active = true; started = now; lastFrame = -1; goodFrames = 0;
        return generation;
    }
    public synchronized void cancel() { generation++; active = false; goodFrames = 0; }
    public synchronized boolean active(long token, long now) {
        if (!active || token != generation) return false;
        if (now < started || now - started >= TIMEOUT_MS) active = false;
        return active;
    }
    public synchronized boolean offer(long token, long now, long timestamp, double score) {
        if (!active(token, now) || timestamp < 0
                || (lastFrame >= 0 && timestamp - lastFrame < INTERVAL_NS)) return false;
        lastFrame = timestamp;
        goodFrames = Double.isFinite(score) && score > THRESHOLD && score <= 1 ? goodFrames + 1 : 0;
        if (goodFrames < REQUIRED) return false;
        active = false; return true;
    }
    public synchronized void missing(long token) {
        if (active && token == generation) goodFrames = 0;
    }
}
