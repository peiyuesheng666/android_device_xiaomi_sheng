// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.keyboard;

import java.util.function.IntPredicate;

/** Tracks submissions, not hardware acknowledgements, on the keyboard link worker. */
final class KeyboardBacklight {
    static final String SETTING = "sheng_keyboard_backlight_percent";
    private int target = -1;
    private int submitted = -1;

    void update(Boolean connected, int percent, int tabletMode) {
        target = !Boolean.TRUE.equals(connected) || percent < 0 || percent > 100
                || (tabletMode != 0 && tabletMode != 1) ? -1 : tabletMode == 1 ? 0 : percent;
    }

    void invalidate() { submitted = -1; }

    void apply(boolean usable, IntPredicate submit) {
        if (usable && target >= 0 && target != submitted && submit.test(target)) {
            submitted = target;
        }
    }
}
