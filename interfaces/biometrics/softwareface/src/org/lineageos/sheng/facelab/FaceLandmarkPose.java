// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.facelab;

/** Geometric guidance from YuNet landmarks; never an attention/liveness claim. */
public final class FaceLandmarkPose {
    private FaceLandmarkPose() {}
    public static float[] estimate(float[] row) {
        if (row == null || row.length != 15) throw new IllegalArgumentException("Landmark row");
        for (float value : row) if (!Float.isFinite(value)) throw new IllegalArgumentException("Landmark value");
        double eyeX = (row[4] + row[6]) * .5, eyeY = (row[5] + row[7]) * .5;
        double eyeDistance = Math.hypot(row[6] - row[4], row[7] - row[5]);
        double mouthY = (row[11] + row[13]) * .5;
        if (eyeDistance < 1 || mouthY - eyeY < 1) return new float[] {Float.NaN, Float.NaN};
        return new float[] {(float)((row[8] - eyeX) / eyeDistance),
                (float)((row[9] - eyeY) / (mouthY - eyeY) - .5)};
    }
}
