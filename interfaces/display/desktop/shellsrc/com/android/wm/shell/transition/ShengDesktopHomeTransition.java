/* SPDX-License-Identifier: Apache-2.0 */
package com.android.wm.shell.transition;

import static android.app.WindowConfiguration.ACTIVITY_TYPE_HOME;
import static android.app.WindowConfiguration.WINDOWING_MODE_FREEFORM;
import static android.view.Display.DEFAULT_DISPLAY;
import static android.view.WindowManager.TRANSIT_OPEN;
import static android.view.WindowManager.TRANSIT_TO_BACK;

import android.animation.ValueAnimator;
import android.os.Build;
import android.util.Log;
import android.view.SurfaceControl;
import android.window.TransitionInfo;
import android.window.RemoteTransition;

import com.android.wm.shell.shared.TransitionUtil;

import java.util.concurrent.Executor;

/** Fade the outgoing home underneath a desktop app's existing Quickstep animation. */
final class ShengDesktopHomeTransition {
    private static final String TAG = "ShengDesktopHome";
    private static final String WALLPAPER =
            "com.android.wm.shell.desktopmode.DesktopWallpaperActivity";
    private final SurfaceControl mHome;
    private final SurfaceControl.Transaction mTransaction = new SurfaceControl.Transaction();
    private ValueAnimator mAnimator;
    private boolean mFinished;

    private ShengDesktopHomeTransition(SurfaceControl home) {
        mHome = home;
    }

    static ShengDesktopHomeTransition prepare(RemoteTransition remote, TransitionInfo info,
            SurfaceControl.Transaction start, SurfaceControl.Transaction finish, Executor executor) {
        if (!"sheng".equals(Build.DEVICE)) return null;
        TransitionInfo.Change home = findHomeToFade(remote.getDebugName(), info);
        if (home == null || !home.getLeash().isValid()) return null;
        ShengDesktopHomeTransition fade = new ShengDesktopHomeTransition(home.getLeash());
        // Quickstep wraps this task leash in its own animation leash. Animate the inner
        // surface only after the remote's initial transaction has committed, so its setup
        // cannot overwrite the first fade frame. Keep app/icon transforms owned by Quickstep.
        finish.setAlpha(home.getLeash(), 1f);
        start.addTransactionCommittedListener(executor, fade::start);
        Log.d(TAG, "Prepared home fade for transition #" + info.getDebugId());
        return fade;
    }

    static TransitionInfo.Change findHomeToFade(String remoteName, TransitionInfo info) {
        if (!"QuickstepLaunch".equals(remoteName) || info.getType() != TRANSIT_OPEN) return null;
        TransitionInfo.Change home = null;
        boolean wallpaperOpening = false;
        boolean desktopAppOpening = false;
        for (TransitionInfo.Change change : info.getChanges()) {
            final var task = change.getTaskInfo();
            if (task == null || task.displayId != DEFAULT_DISPLAY) continue;
            if (task.getActivityType() == ACTIVITY_TYPE_HOME && change.getMode() == TRANSIT_TO_BACK) {
                home = change;
            }
            if (!TransitionUtil.isOpeningType(change.getMode())) continue;
            if (task.baseIntent.getComponent() != null
                    && "com.android.systemui".equals(task.baseIntent.getComponent().getPackageName())
                    && WALLPAPER.equals(task.baseIntent.getComponent().getClassName())) {
                wallpaperOpening = true;
            } else if (task.getWindowingMode() == WINDOWING_MODE_FREEFORM
                    && task.getActivityType() != ACTIVITY_TYPE_HOME) {
                desktopAppOpening = true;
            }
        }
        return wallpaperOpening && desktopAppOpening ? home : null;
    }

    private void start() {
        if (mFinished || !mHome.isValid()) return;
        mAnimator = ValueAnimator.ofFloat(1f, 0f);
        mAnimator.setDuration(250);
        mAnimator.addUpdateListener(animation -> {
            if (!mFinished && mHome.isValid()) {
                mTransaction.setAlpha(mHome, (Float) animation.getAnimatedValue()).apply();
            }
        });
        mAnimator.start();
    }

    void onMerge(TransitionInfo info, SurfaceControl.Transaction start) {
        if (mFinished) return;
        for (TransitionInfo.Change change : info.getChanges()) {
            final var task = change.getTaskInfo();
            if (task != null && task.displayId == DEFAULT_DISPLAY
                    && task.getActivityType() == ACTIVITY_TYPE_HOME
                    && TransitionUtil.isOpeningType(change.getMode())) {
                // Swiping home/back interrupts the fade immediately; never leave home invisible.
                finish();
                if (mHome.isValid()) start.setAlpha(mHome, 1f);
                return;
            }
        }
    }

    void finish() {
        if (mFinished) return;
        mFinished = true;
        if (mAnimator != null) mAnimator.cancel();
        mTransaction.close();
    }
}
