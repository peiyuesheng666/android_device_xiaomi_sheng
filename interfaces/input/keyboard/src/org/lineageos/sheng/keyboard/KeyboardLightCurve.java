// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.keyboard;

/** Trial ambient-light policy, not sensor calibration or claimed OEM calibration. */
final class KeyboardLightCurve {
    static int percent(float lux) {
        if (Float.isNaN(lux) || Float.isInfinite(lux) || lux < 0) return -1;
        double percent = Math.max(0, Math.min(100, 100 - 45 * Math.log10(1 + lux)));
        return (int) Math.round(percent / 5) * 5;
    }
}
