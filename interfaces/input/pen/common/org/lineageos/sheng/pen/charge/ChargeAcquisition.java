// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.pen.charge;

/** Presentation grace period for a newly attached pen; never changes charger data. */
public final class ChargeAcquisition {
    public static final long TIMEOUT_MS = 3500;
    private long attachedAt = -1;
    private boolean resolved;

    public ChargeStatus update(ChargeStatus raw, long elapsedMillis) {
        if (raw.state == ChargeStatus.State.DETACHED) {
            attachedAt = -1;
            resolved = false;
            return raw;
        }
        if (attachedAt < 0) {
            if (!raw.docked()) return raw;
            attachedAt = elapsedMillis;
        }
        if (raw.charging() || raw.state == ChargeStatus.State.FULL) {
            resolved = true;
            return raw;
        }
        if (resolved) return raw;
        // Missing/changing detail must not restart the timeout on every poll.
        return ChargeStatus.fromProvider(elapsedMillis - attachedAt < TIMEOUT_MS
                ? "ACQUIRING" : "MISALIGNED", -1, null);
    }
}
