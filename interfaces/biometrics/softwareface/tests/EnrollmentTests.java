// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.facelab;

/** Synthetic geometry and credential/camera lifecycle; no face or credential data. */
public final class EnrollmentTests {
    private static int checks;
    private static void check(boolean condition, String detail) {
        checks++; if (!condition) throw new AssertionError(detail);
    }
    private static void invalid(Runnable action) {
        try { action.run(); } catch (IllegalArgumentException expected) { checks++; return; }
        throw new AssertionError("Invalid geometry admitted");
    }
    public static void main(String[] args) {
        for (int[] frame : new int[][]{{1280,960}, {960,1280}, {640,480}, {480,640}}) {
            double minimum = Math.min(frame[0],frame[1]) * .30;
            check(!EnrollmentFraming.closeEnough(minimum-1,minimum+40,frame[0],frame[1]),
                    "Distant face width waits for user to approach");
            check(!EnrollmentFraming.closeEnough(minimum+40,minimum-1,frame[0],frame[1]),
                    "Distant face height waits for user to approach");
            check(EnrollmentFraming.closeEnough(minimum,minimum,frame[0],frame[1]),
                    "Boundary is usable in portrait and landscape at both resolutions");
        }
        // This face passed the old 90-pixel detector floor but is too far for enrollment.
        check(!EnrollmentFraming.closeEnough(200,260,1280,960),"Old comparison-sized face excluded from enrollment");
        check(EnrollmentFraming.closeEnough(320,420,1280,960),"Larger enrollment face accepted");
        invalid(() -> EnrollmentFraming.closeEnough(Double.NaN,320,1280,960));
        invalid(() -> EnrollmentFraming.closeEnough(320,Double.POSITIVE_INFINITY,1280,960));
        invalid(() -> EnrollmentFraming.closeEnough(0,320,1280,960));
        invalid(() -> EnrollmentFraming.closeEnough(320,320,0,960));

        EnrollmentRequest request = new EnrollmentRequest();
        check(!request.pending(1000) && !request.consume(1000),"No capture before a user request");
        check(!request.result(true,1000),"Unsolicited credential result cannot authorize capture");
        check(request.confirm(),"User starts platform credential confirmation");
        check(!request.confirm(),"Repeated tap cannot launch a second credential activity");
        check(!request.consume(1000),"Camera cannot consume unconfirmed authorization");
        request.cancel(true);
        check(request.confirming(),"Credential activity pause preserves only pending confirmation");
        check(request.result(true,1000),"Successful platform result arms the requested enrollment");
        check(request.pending(1001),"Authorization waits for resumed activity and camera surface");
        check(request.consume(1001),"First configured camera may begin collection");
        check(!request.consume(1002),"Repeated resume/configuration callbacks cannot restart collection");
        check(!request.result(true,1003),"Replayed credential result cannot start another capture");

        request.confirm(); request.result(true,2000);
        check(request.pending(2000+EnrollmentRequest.VALID_MS-1),"Authorization valid just before deadline");
        check(!request.consume(2000+EnrollmentRequest.VALID_MS),"Slow camera cannot begin at expiration");
        request.confirm(); request.result(true,40000);
        check(!request.pending(39999),"Backward monotonic time fails closed");
        request.confirm(); request.cancel(false);
        check(!request.result(true,50000),"Stop/delete/comparison cancels confirmation and rejects delayed result");
        request.confirm(); request.result(true,50000); request.cancel(false);
        check(!request.consume(50001),"Stop while opening camera cancels authorized collection");
        request.confirm(); request.result(true,60000); request.cancel(true);
        check(!request.consume(60001),"Ordinary pause cancels an already approved request");
        request.confirm();
        check(!request.result(false,70000) && !request.pending(70001),"Cancelled password verification keeps camera off");
        check(!new EnrollmentRequest().consume(70002),"Activity recreation cannot inherit capture authorization");
        System.out.println("PASS "+checks+" enrollment checks");
    }
}
