// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.facelab;

/** Enrollment needs a larger face; comparison retains its existing detection floor. */
public final class EnrollmentFraming {
    private EnrollmentFraming() {}

    public static boolean closeEnough(double faceWidth, double faceHeight, int width, int height) {
        if (width <= 0 || height <= 0 || !Double.isFinite(faceWidth)
                || !Double.isFinite(faceHeight) || faceWidth <= 0 || faceHeight <= 0)
            throw new IllegalArgumentException("Invalid face geometry");
        double minimum = Math.min(width, height) * .30;
        return faceWidth >= minimum && faceHeight >= minimum;
    }
}
