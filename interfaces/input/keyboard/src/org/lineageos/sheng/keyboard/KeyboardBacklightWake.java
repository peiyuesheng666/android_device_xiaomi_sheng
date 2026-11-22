// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.keyboard;

/** One activation for an explicit settings change, never for ambient updates. */
final class KeyboardBacklightWake {
    private boolean initialized;
    private int manual;
    private boolean automatic;

    boolean update(int nextManual, boolean nextAutomatic, boolean usable, boolean awake) {
        boolean changed = initialized && (manual != nextManual || automatic != nextAutomatic);
        initialized = true;
        manual = nextManual;
        automatic = nextAutomatic;
        return changed && usable && !awake && nextManual >= 0 && nextManual <= 100;
    }
}
