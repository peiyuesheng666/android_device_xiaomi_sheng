// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.keyboard;

public final class KeyboardLightCurveTest {
    public static void main(String[] args) {
        for (float invalid : new float[]{-1, Float.NaN, Float.POSITIVE_INFINITY}) {
            if (KeyboardLightCurve.percent(invalid) != -1) throw new AssertionError("Invalid sample");
        }
        if (KeyboardLightCurve.percent(0) != 100) throw new AssertionError("Dark room");
        if (KeyboardLightCurve.percent(10000) != 0) throw new AssertionError("Bright room");
        int previous = 100;
        for (int lux = 0; lux <= 10000; lux++) {
            int next = KeyboardLightCurve.percent(lux);
            if (next < 0 || next > previous || next % 5 != 0) throw new AssertionError("Curve at " + lux);
            previous = next;
        }
        System.out.println("PASS keyboard trial ambient curve: bounds, invalid samples, monotonicity");
    }
}
