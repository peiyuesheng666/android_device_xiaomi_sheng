// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.face;

import java.security.SecureRandom;

public final class ChallengeLedgerTests {
    private static int checks;
    private static void check(boolean value) {
        checks++; if (!value) throw new AssertionError("Check " + checks);
    }
    public static void main(String[] args) {
        long[] now = {1000};
        ChallengeLedger a = new ChallengeLedger(new SecureRandom(), () -> now[0]);
        ChallengeLedger b = new ChallengeLedger(new SecureRandom(), () -> now[0]);
        long first = a.generate(), second = a.generate();
        check(first != 0 && second != 0 && first != second);
        check(a.valid(first) && a.valid(second)); // A second challenge preserves the first.
        check(!b.valid(first)); // Sessions/users cannot share challenge authority.
        a.revoke(second); check(!a.valid(second) && a.valid(first));
        check(a.consume(first)); check(!a.consume(first)); // Replay rejection.
        a.revoke(123); check(!a.valid(123));
        long expiring = a.generate();
        now[0] += ChallengeLedger.LIFETIME_MS - 1; check(a.valid(expiring));
        now[0]++; check(!a.valid(expiring));
        long rollback = a.generate(); now[0]--; check(!a.valid(rollback));
        for (int i = 0; i < 32; i++) a.generate();
        boolean bounded = false;
        try { a.generate(); } catch (IllegalStateException expected) { bounded = true; }
        check(bounded); a.clear(); check(a.generate() != 0);
        System.out.println("Challenge ledger: " + checks + " checks passed");
    }
}
