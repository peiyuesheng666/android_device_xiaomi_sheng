// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

import android.os.Handler;
import android.os.UEventObserver;
import java.util.function.IntConsumer;

/** Only stock MIPP frequency requests enter the serialized pen actor. */
final class PenPanelObserver extends UEventObserver {
    private final Handler handler;
    private final IntConsumer callback;
    private volatile boolean observing;
    PenPanelObserver(Handler handler, IntConsumer callback) {
        this.handler = handler; this.callback = callback;
    }
    void start() { observing = true; startObserving("MIPP_PEN_STATE="); }
    void close() { observing = false; stopObserving(); }
    @Override public void onUEvent(UEvent event) {
        if (!observing) return;
        final int value;
        try { value = Integer.parseInt(event.get("MIPP_PEN_STATE")); }
        catch (RuntimeException error) { return; }
        handler.post(() -> { if (observing) callback.accept(value); });
    }
}
