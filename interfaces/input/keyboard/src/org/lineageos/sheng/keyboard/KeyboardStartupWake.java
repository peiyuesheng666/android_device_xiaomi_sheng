// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.keyboard;

/** Stock MiuiKeyboardManager's bounded screen/attachment activation window. */
final class KeyboardStartupWake {
    private boolean usable;
    private long until;
    private long next;

    void resumed(boolean available, long now) {
        if (!available) return;
        usable = true;
        until = now + 120000;
        next = now + 12000;
    }

    boolean update(boolean available, long now) {
        if (!available) {
            usable = false;
            until = next = 0;
            return false;
        }
        if (!usable) {
            resumed(true, now);
        }
        if (now >= until || now < next) return false;
        next = now + 12000;
        return true;
    }
}
