// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.facelab;

/** One user-requested enrollment, authorized by the platform credential result. */
public final class EnrollmentRequest {
    public static final long VALID_MS = 30_000;
    private boolean confirming, ready;
    private long approvedAt;

    public synchronized boolean confirm() {
        if (confirming) return false;
        ready = false; confirming = true; return true;
    }
    public synchronized boolean confirming() { return confirming; }
    public synchronized boolean result(boolean approved, long now) {
        if (!confirming) return false;
        confirming = false; ready = approved && now >= 0; approvedAt = now;
        return ready;
    }
    public synchronized boolean pending(long now) {
        if (ready && (now < approvedAt || now - approvedAt >= VALID_MS)) ready = false;
        return ready;
    }
    public synchronized boolean consume(long now) {
        if (!pending(now)) return false;
        ready = false; return true;
    }
    public synchronized void cancel(boolean preserveConfirmation) {
        ready = false;
        if (!preserveConfirmation) confirming = false;
    }
}
