/* SPDX-License-Identifier: Apache-2.0 */
package com.android.wm.shell.transition;

import android.app.ActivityManager.RunningTaskInfo;
import android.app.WindowConfiguration;
import android.content.ComponentName;
import android.content.Intent;
import android.view.SurfaceControl;
import android.view.WindowManager;
import android.window.TransitionInfo;

/** Runs on Android; checks that ordinary launches and external displays are excluded. */
public final class ShengDesktopHomeTransitionProbe {
    private static TransitionInfo.Change change(int activityType, int windowingMode,
            int mode, int display, String component) {
        RunningTaskInfo task = new RunningTaskInfo();
        task.displayId = display;
        task.configuration.windowConfiguration.setActivityType(activityType);
        task.configuration.windowConfiguration.setWindowingMode(windowingMode);
        task.baseIntent = new Intent();
        if (component != null) task.baseIntent.setComponent(ComponentName.unflattenFromString(component));
        TransitionInfo.Change change = new TransitionInfo.Change(null, new SurfaceControl());
        change.setMode(mode);
        change.setTaskInfo(task);
        return change;
    }

    private static TransitionInfo scene(boolean wallpaper, int appMode, int display) {
        TransitionInfo info = new TransitionInfo(WindowManager.TRANSIT_OPEN, 0);
        info.addChange(change(WindowConfiguration.ACTIVITY_TYPE_HOME,
                WindowConfiguration.WINDOWING_MODE_FULLSCREEN, WindowManager.TRANSIT_TO_BACK,
                display, null));
        info.addChange(change(WindowConfiguration.ACTIVITY_TYPE_STANDARD, appMode,
                WindowManager.TRANSIT_OPEN, display, "com.android.settings/.Settings"));
        if (wallpaper) info.addChange(change(WindowConfiguration.ACTIVITY_TYPE_STANDARD,
                WindowConfiguration.WINDOWING_MODE_FULLSCREEN, WindowManager.TRANSIT_TO_FRONT,
                display, "com.android.systemui/com.android.wm.shell.desktopmode.DesktopWallpaperActivity"));
        return info;
    }

    private static void check(String name, TransitionInfo info, String remote, boolean expected) {
        try {
            boolean selected = ShengDesktopHomeTransition.findHomeToFade(remote, info) != null;
            if (selected != expected) throw new AssertionError(name);
            System.out.println("PASS " + name);
        } finally {
            info.releaseAllSurfaces();
        }
    }

    public static void main(String[] args) {
        int freeform = WindowConfiguration.WINDOWING_MODE_FREEFORM;
        check("desktop launch", scene(true, freeform, 0), "QuickstepLaunch", true);
        check("fullscreen launch", scene(true, WindowConfiguration.WINDOWING_MODE_FULLSCREEN, 0),
                "QuickstepLaunch", false);
        check("no wallpaper replacement", scene(false, freeform, 0), "QuickstepLaunch", false);
        check("external desktop", scene(true, freeform, 1), "QuickstepLaunch", false);
        check("other animation", scene(true, freeform, 0), "OtherRemote", false);
        TransitionInfo returningHome = scene(true, freeform, 0);
        returningHome.getChanges().get(0).setMode(WindowManager.TRANSIT_TO_FRONT);
        check("returning home", returningHome, "QuickstepLaunch", false);
        TransitionInfo noHome = scene(true, freeform, 0);
        noHome.getChanges().remove(0).getLeash().release();
        check("no outgoing home", noHome, "QuickstepLaunch", false);
        System.out.println("PASS 7 desktop home transition cases");
    }
}
