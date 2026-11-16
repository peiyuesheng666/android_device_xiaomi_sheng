// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.RemoteException;
import java.util.HashMap;
import java.util.Map;

/** A visible Settings window owns a death-linked presentation suppression token. */
final class PenPopupVisibility {
    private static final Map<IBinder, IBinder.DeathRecipient> windows = new HashMap<>();
    private static final Handler main = new Handler(Looper.getMainLooper());
    private static Runnable changed = () -> {};

    static synchronized boolean settingsVisible() { return !windows.isEmpty(); }
    static synchronized void observe(Runnable listener) { changed = listener; }

    static synchronized void setVisible(IBinder token, boolean visible) {
        if (token == null) throw new IllegalArgumentException("Missing Settings window token");
        boolean before = !windows.isEmpty();
        if (visible && !windows.containsKey(token)) {
            IBinder.DeathRecipient death = () -> setVisible(token, false);
            try { token.linkToDeath(death, 0); }
            catch (RemoteException gone) { return; }
            windows.put(token, death);
        } else if (!visible) {
            IBinder.DeathRecipient death = windows.remove(token);
            if (death != null) token.unlinkToDeath(death, 0);
        }
        if (before != !windows.isEmpty()) main.post(changed);
    }
}
