// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.face;

import android.view.Surface;

/** Only the real engine supplies frames in production; tests use no camera. */
public interface FaceCapture {
    /** Must be implemented and validated before accepting REQUIRE_DIVERSE_POSES. */
    default boolean supportsDiversePoses() { return false; }
    interface Listener {
        void frame(long timestampNs, float[] normalizedEmbedding, byte acquiredInfo, int vendorCode, byte enrollmentStage,
                float pan, float tilt);
        void error(byte error);
    }
    void start(boolean enrolling, Surface preview, boolean diversePoses, Listener listener) throws Exception;
    void stop();
}
