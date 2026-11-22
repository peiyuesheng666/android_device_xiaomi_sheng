// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.keyboard;

import java.util.ArrayList;
import java.util.List;
import java.util.function.IntPredicate;

public final class KeyboardBacklightTest {
    public static void main(String[] args) {
        var control = new KeyboardBacklight();
        var sent = new ArrayList<Integer>();
        IntPredicate send = sent::add;
        control.apply(true, send); // Not configured.
        control.update(null, 60, 0);
        control.apply(true, send);
        control.update(true, 60, -1);
        control.apply(true, send);
        control.update(true, 101, 0);
        control.apply(true, send);
        control.update(true, 60, 0);
        control.apply(false, send); // Asleep, unverified, or unsupported.
        check(sent, List.of());
        control.apply(true, value -> false); // Transport failure is not cached.
        control.apply(true, send);
        control.apply(true, send);
        check(sent, List.of(60));
        control.update(true, 60, 1);
        control.apply(true, send);
        control.update(true, 60, 0);
        control.apply(true, send);
        control.invalidate(); // Reconnect or wake.
        control.apply(true, send);
        control.update(false, 100, 0);
        control.apply(true, send);
        check(sent, List.of(60, 0, 60, 60));
        System.out.println("PASS keyboard backlight submission lifecycle");
    }

    private static void check(List<Integer> actual, List<Integer> expected) {
        if (!actual.equals(expected)) throw new AssertionError(actual + " != " + expected);
    }
}
