// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.keyboard;

public final class KeyboardBacklightWakeTest {
    private static void check(boolean value) { if (!value) throw new AssertionError(); }
    public static void main(String[] args) {
        KeyboardBacklightWake wake = new KeyboardBacklightWake();
        check(!wake.update(50, false, true, false));
        for (int i = 0; i < 1000; i++) check(!wake.update(50, false, true, false));
        check(wake.update(100, false, true, false));
        check(!wake.update(100, false, true, false));
        check(wake.update(100, true, true, false));
        for (int i = 0; i < 1000; i++) check(!wake.update(100, true, true, false));
        check(!wake.update(0, false, false, false));
        check(!wake.update(0, false, true, false));
        check(!wake.update(50, false, true, true));
        check(!wake.update(-1, false, true, false));
        check(!wake.update(101, false, true, false));
        System.out.println("PASS explicit-change wake and 2000 idle polls");
    }
}
