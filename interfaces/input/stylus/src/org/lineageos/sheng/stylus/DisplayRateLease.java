// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

import android.content.Context;
import android.hardware.display.DisplayManager;
import android.hardware.display.IDisplayManager;
import android.os.Binder;
import android.os.IBinder;
import android.os.RemoteException;
import android.os.ServiceManager;
import android.view.Display;

/** A removable display-mode request; user refresh-rate settings are never written. */
public final class DisplayRateLease implements AutoCloseable {
    private final DisplayManager displays;
    private final IDisplayManager service;
    private final IBinder token = new Binder();
    private boolean held;

    public DisplayRateLease(Context context) {
        displays = context.getSystemService(DisplayManager.class);
        service = IDisplayManager.Stub.asInterface(ServiceManager.getService("display"));
        if (displays == null || service == null) {
            throw new IllegalStateException("Display service unavailable");
        }
    }

    public synchronized void acquire(float supportedRate) throws RemoteException {
        if (held) return;
        if (!Float.isFinite(supportedRate) || supportedRate <= 0) {
            throw new IllegalArgumentException("Invalid pen display rate");
        }
        Display display = displays.getDisplay(Display.DEFAULT_DISPLAY);
        if (display == null) throw new IllegalStateException("Built-in display unavailable");
        Display.Mode current = display.getMode();
        int selected = 0;
        for (Display.Mode mode : display.getSupportedModes()) {
            if (mode.getPhysicalWidth() == current.getPhysicalWidth()
                    && mode.getPhysicalHeight() == current.getPhysicalHeight()
                    && Math.abs(mode.getRefreshRate() - supportedRate) < 0.1f) {
                selected = mode.getModeId();
                break;
            }
        }
        if (selected == 0) throw new IllegalStateException("Supported pen display mode unavailable");
        // This higher-priority system vote preserves Settings and is removed by
        // DisplayManager when this token's process dies. Non-VRR panels also
        // accept this cap; requestDisplayModes is ignored for such panels.
        held = true;
        service.requestMaxRefreshRate(token, Display.DEFAULT_DISPLAY, supportedRate);
    }

    @Override public synchronized void close() throws RemoteException {
        if (!held) return;
        service.requestMaxRefreshRate(token, Display.DEFAULT_DISPLAY, 0);
        held = false;
    }
}
