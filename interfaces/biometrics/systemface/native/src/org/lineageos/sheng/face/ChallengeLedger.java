// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.face;

import java.security.SecureRandom;
import java.util.HashMap;
import java.util.Map;
import java.util.function.LongSupplier;

/** Per-session, per-user challenges. All expiry decisions use monotonic time. */
public final class ChallengeLedger {
    public static final long LIFETIME_MS = 120_000;
    private static final int MAX_OUTSTANDING = 32;
    private final Map<Long, Long> challenges = new HashMap<>();
    private final SecureRandom random;
    private final LongSupplier clock;

    public ChallengeLedger(SecureRandom random, LongSupplier clock) {
        this.random = random;
        this.clock = clock;
    }

    public synchronized long generate() {
        long now = clock.getAsLong();
        prune(now);
        if (challenges.size() >= MAX_OUTSTANDING) {
            throw new IllegalStateException("Too many outstanding challenges");
        }
        long challenge;
        do { challenge = random.nextLong(); }
        while (challenge == 0 || challenges.containsKey(challenge));
        challenges.put(challenge, now);
        return challenge;
    }

    public synchronized boolean valid(long challenge) {
        prune(clock.getAsLong());
        return challenge != 0 && challenges.containsKey(challenge);
    }

    /** Consume only after cryptographic verification and before enrollment begins. */
    public synchronized boolean consume(long challenge) {
        return valid(challenge) && challenges.remove(challenge) != null;
    }

    public synchronized void revoke(long challenge) { challenges.remove(challenge); }
    public synchronized void clear() { challenges.clear(); }

    private void prune(long now) {
        challenges.entrySet().removeIf(e -> now < e.getValue()
                || now - e.getValue() >= LIFETIME_MS);
    }
}
