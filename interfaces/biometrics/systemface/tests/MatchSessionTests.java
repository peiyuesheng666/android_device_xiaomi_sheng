// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.facelab;

public final class MatchSessionTests {
    private static int checks;
    private static void check(boolean result, String detail) {
        checks++; if (!result) throw new AssertionError(detail);
    }
    public static void main(String[] args) {
        MatchSession session = new MatchSession();
        check(!session.offer(0,0,0,1), "No matching before an unlock attempt");
        long token = session.begin(1000);
        check(!session.offer(token,1000,0,.51), "First qualifying frame waits");
        check(!session.offer(token,1100,100_000_000L,.6), "Second qualifying frame waits");
        check(session.offer(token,1200,200_000_000L,.7), "Three spaced qualifying frames finish");
        check(!session.offer(token,1300,300_000_000L,1), "Completed attempt cannot grant twice");
        token = session.begin(2000);
        check(!session.offer(token,2000,0,.8), "New attempt starts its own evidence");
        check(!session.offer(token,2050,50_000_000L,.9), "Duplicate/too-close frame does not advance");
        check(!session.offer(token,2100,100_000_000L,.8), "Only second independent frame admitted");
        session.missing(token);
        check(!session.offer(token,2200,200_000_000L,.8), "Missing face resets accumulated matches");
        check(!session.offer(token,2300,300_000_000L,.5), "Exact proposed boundary is not greater than .5");
        check(!session.offer(token,2400,400_000_000L,.8), "Nonmatching frame requires a fresh streak");
        check(!session.offer(token,2500,500_000_000L,Double.NaN), "Nonfinite score cannot grant");
        check(!session.offer(token,2600,600_000_000L,1.1), "Invalid score cannot grant");
        session.cancel();
        check(!session.offer(token,2700,700_000_000L,1), "Cancellation rejects delayed result");
        long old = token; token = session.begin(4000);
        check(!session.active(old,1000), "Old callback rejected without expiring new session");
        check(session.active(token,4001), "New session remains active after stale callback");
        check(!session.offer(token,9000,0,1), "Timeout boundary rejects authentication");
        check(!session.active(token,9001), "Timed-out attempt remains inactive");
        token = session.begin(10000);
        check(!session.active(token,9999), "Backward monotonic time fails closed");
        System.out.println("PASS " + checks + " match-session checks");
    }
}
