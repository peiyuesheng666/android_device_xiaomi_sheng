// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

import android.os.SystemClock;
import org.lineageos.sheng.pen.charge.ChargeAcquisition;
import org.lineageos.sheng.pen.charge.ChargeStatus;

/** One attachment timer shared by the popup and the Settings content provider. */
final class PenChargingState {
    private static final ChargeAcquisition acquisition = new ChargeAcquisition();

    static synchronized ChargeStatus read() {
        return acquisition.update(ChargeStatus.read(), SystemClock.elapsedRealtime());
    }
}
