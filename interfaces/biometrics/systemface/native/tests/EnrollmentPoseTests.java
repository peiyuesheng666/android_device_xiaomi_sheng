// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.face;

import org.lineageos.sheng.facelab.FaceLandmarkPose;

public final class EnrollmentPoseTests {
    private static int checks;
    private static void check(boolean value) { checks++; if (!value) throw new AssertionError("Pose check " + checks); }
    public static void main(String[] args) {
        float[] row = {0,0,100,100,20,30,80,30,50,50,35,70,65,70,1};
        float[] pose = FaceLandmarkPose.estimate(row); check(pose[0] == 0 && pose[1] == 0);
        row[8] = 56; check(Math.abs(FaceLandmarkPose.estimate(row)[0] - .1) < .00001);
        for (int i=4; i<14; i++) row[i] = row[i]*2+20;
        check(Math.abs(FaceLandmarkPose.estimate(row)[0] - .1) < .00001);
        EnrollmentPoseGate gate = new EnrollmentPoseGate(true);
        check(gate.direction() == 0);
        check(!gate.offer(0,Float.NaN,0) && !gate.offer(-1,0,0));
        for (int i=0;i<4;i++) check(gate.offer(i*250_000_000L,0,0));
        check(gate.count() == 4 && gate.direction() == -1);
        check(!gate.offer(1_000_000_000L,0,0));
        for (int i=4;i<8;i++) check(gate.offer(i*250_000_000L,-.12f,0));
        check(gate.count() == 8 && gate.direction() == 1);
        check(!gate.offer(2_000_000_000L,-.12f,0));
        for (int i=8;i<12;i++) check(gate.offer(i*250_000_000L,.12f,0));
        check(!gate.offer(3_000_000_000L,.12f,0));
        EnrollmentPoseGate accessible = new EnrollmentPoseGate(false);
        check(accessible.offer(0,0,0)); check(!accessible.offer(0,0,0));
        check(!accessible.offer(250_000_000L,0,.4f));
        for (int i=1;i<12;i++) check(accessible.offer(i*250_000_000L,0,0));
        check(accessible.count()==12 && accessible.direction()==0);
        System.out.println("Landmark and enrollment pose: " + checks + " checks passed");
    }
}
