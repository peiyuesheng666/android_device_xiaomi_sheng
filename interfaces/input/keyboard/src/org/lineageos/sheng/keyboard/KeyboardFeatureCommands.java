// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.keyboard;

import java.util.HashMap;
import java.util.Map;
import java.util.function.BooleanSupplier;

/** One bounded replay of a normal feature request, cancelled by its effect ACK. */
final class KeyboardFeatureCommands {
    interface Scheduler { void postDelayed(Runnable task, long delay); void remove(Runnable task); }
    interface Sender { boolean send(int command, boolean enabled); }
    private final Scheduler scheduler;
    private final Sender sender;
    private final BooleanSupplier usable;
    private final Map<Integer, Pending> pending = new HashMap<>();

    KeyboardFeatureCommands(Scheduler scheduler, Sender sender, BooleanSupplier usable) {
        this.scheduler = scheduler; this.sender = sender; this.usable = usable;
    }

    boolean send(int command, boolean enabled) {
        Pending old = pending.remove(command);
        if (old != null) scheduler.remove(old);
        if (!usable.getAsBoolean() || !sender.send(command, enabled)) return false;
        Pending request = new Pending(command, enabled);
        pending.put(command, request);
        scheduler.postDelayed(request, 50);
        return true;
    }

    void acknowledge(int command, int value) {
        Pending request = pending.get(command);
        if (request != null && value == (request.enabled ? 1 : 0)) {
            pending.remove(command); scheduler.remove(request);
        }
    }

    void clear() {
        for (Pending request : pending.values()) scheduler.remove(request);
        pending.clear();
    }

    private final class Pending implements Runnable {
        final int command; final boolean enabled;
        Pending(int command, boolean enabled) { this.command = command; this.enabled = enabled; }
        @Override public void run() {
            if (pending.get(command) != this) return;
            pending.remove(command);
            if (usable.getAsBoolean()) sender.send(command, enabled);
        }
    }
}
