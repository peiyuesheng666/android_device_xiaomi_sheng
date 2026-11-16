// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

import org.lineageos.sheng.pen.charge.ChargeStatus;

/** Main-thread presentation state for one physical attachment. */
final class PenChargeSession {
    private boolean attached, shown, confirmed, dismissed;

    void update(ChargeStatus status) {
        if (status.state == ChargeStatus.State.DETACHED) {
            attached = shown = confirmed = dismissed = false;
        } else if (status.docked()) attached = true;
    }

    boolean hasAttachment() { return attached; }

    boolean shouldShow(ChargeStatus status, boolean interactive) {
        // Acquisition stays in Settings. The attachment card needs either real
        // charging data or the acquisition deadline's placement/failure result.
        boolean ready = isConfirmed(status) || status.state == ChargeStatus.State.MISALIGNED;
        return interactive && !dismissed && ready
                && (!shown || (isConfirmed(status) && !confirmed));
    }

    void markShown(ChargeStatus status) {
        shown = true;
        if (isConfirmed(status)) confirmed = true;
    }

    void dismiss() { dismissed = true; }

    private boolean isConfirmed(ChargeStatus status) {
        return status.state == ChargeStatus.State.CHARGING || status.state == ChargeStatus.State.FULL;
    }
}
