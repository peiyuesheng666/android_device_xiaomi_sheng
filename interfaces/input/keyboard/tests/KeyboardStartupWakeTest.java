// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.keyboard;

public final class KeyboardStartupWakeTest {
    private static void check(boolean value) { if (!value) throw new AssertionError(); }
    public static void main(String[] args) {
        KeyboardStartupWake wake = new KeyboardStartupWake();
        check(!wake.update(true, 1000));
        int sends = 0;
        for (long t = 1250; t <= 301000; t += 250) {
            if (wake.update(true, t)) {
                check(t < 121000);
                sends++;
            }
        }
        check(sends == 9);
        check(!wake.update(false, 302000));
        check(!wake.update(true, 303000));
        check(wake.update(true, 315000));
        check(!wake.update(false, 315001));
        check(!wake.update(false, 400000));
        wake.resumed(false, 410000);
        check(!wake.update(true, 420000));
        wake.resumed(true, 600000);
        check(!wake.update(true, 611999));
        check(wake.update(true, 612000));
        check(!wake.update(true, 720000));
        System.out.println("PASS 12s cadence, 120s bound, detach/screen/fold cancellation and rearm");
    }
}
