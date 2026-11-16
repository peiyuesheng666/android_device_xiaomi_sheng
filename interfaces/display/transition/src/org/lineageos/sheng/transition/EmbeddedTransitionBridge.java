// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.transition;

import android.os.Build;
import android.util.Log;
import android.view.WindowManager;
import android.window.RemoteTransition;
import android.window.TransitionInfo;
import java.util.ArrayList;

/** Adapter used only by the device's generated SystemUI variant. */
public final class EmbeddedTransitionBridge {
    public static boolean shouldWait(RemoteTransition remote, TransitionInfo info) {
        if (!"sheng".equals(Build.DEVICE) || !"QuickstepLaunch".equals(remote.getDebugName())
                || info.getType() != WindowManager.TRANSIT_OPEN) return false;
        ArrayList<EmbeddedLaunchPolicy.Change> changes = new ArrayList<>();
        for (TransitionInfo.Change change : info.getChanges()) {
            changes.add(new EmbeddedLaunchPolicy.Change(change.getMode(),
                    change.hasFlags(TransitionInfo.FLAG_IN_TASK_WITH_EMBEDDED_ACTIVITY),
                    change.getStartAbsBounds().equals(change.getEndAbsBounds())
                            && change.getStartDisplayId() == change.getEndDisplayId()));
        }
        boolean wait = EmbeddedLaunchPolicy.shouldWait(Build.DEVICE, remote.getDebugName(),
                info.getType(), WindowManager.TRANSIT_OPEN, WindowManager.TRANSIT_CHANGE, changes);
        if (wait) Log.i("RemoteTransitionHandler", "sheng: Queue embedded transition #"
                + info.getDebugId() + " until Quickstep launch completes");
        return wait;
    }
    private EmbeddedTransitionBridge() {}
}
