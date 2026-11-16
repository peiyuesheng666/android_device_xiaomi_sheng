// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.face;

/** Per-user metadata and encrypted templates. Failures must survive service restarts. */
public interface FaceRepository {
    int enrollmentId() throws Exception;
    float[][] load() throws Exception;
    void enroll(int id, float[][] samples, byte[] features) throws Exception;
    byte[] features() throws Exception;
    void remove() throws Exception;
    int failures() throws Exception;
    void failures(int count) throws Exception;
}
