// SPDX-License-Identifier: Apache-2.0
package com.android.settings.sheng;

import android.app.WindowConfiguration;
import android.app.ActivityManager;
import android.app.ActivityTaskManager;
import android.app.settings.SettingsEnums;
import android.content.ContentResolver;
import android.hardware.display.DisplayManager;
import android.os.Bundle;
import android.os.Debug;
import android.os.Handler;
import android.os.Looper;
import android.os.RemoteException;
import android.os.SystemClock;
import android.provider.Settings;
import android.util.Log;
import android.view.Display;
import android.view.IWindowManager;
import android.view.WindowManagerGlobal;
import android.widget.Toast;
import android.window.DesktopExperienceFlags;

import androidx.preference.SwitchPreferenceCompat;

import com.android.settings.R;
import com.android.settings.SettingsPreferenceFragment;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutorService;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Native Settings page. WindowManager applies and persists the display mode live. */
public final class DesktopModeSettings extends SettingsPreferenceFragment {
    private final Handler mHandler = new Handler(Looper.getMainLooper());
    private SwitchPreferenceCompat mDesktop;
    private final Runnable mRefresh = this::refresh;
    private final android.database.ContentObserver mObserver =
            new android.database.ContentObserver(mHandler) {
                @Override public void onChange(boolean selfChange) { refresh(); }
            };
    @Override public int getMetricsCategory() { return SettingsEnums.SETTINGS_SYSTEM_CATEGORY; }
    @Override protected int getPreferenceScreenResId() { return R.xml.sheng_desktop_settings; }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        mDesktop = findPreference("sheng_desktop_enabled");
        Controller.restoreExternalDefault(getContext());
        mDesktop.setOnPreferenceChangeListener((preference, value) -> {
            apply((Boolean) value); return false;
        });

    }
    @Override public void onResume() {
        super.onResume();
        getActivity().setTitle(R.string.sheng_desktop_title);
        Controller.LISTENERS.add(mRefresh);
        getContext().getContentResolver().registerContentObserver(
                Settings.Global.getUriFor(Controller.ENABLED), false, mObserver);
        getContext().getContentResolver().registerContentObserver(
                Settings.Secure.getUriFor(Settings.Secure.MIRROR_BUILT_IN_DISPLAY), false, mObserver);
        refresh();
    }
    @Override public void onPause() {
        Controller.LISTENERS.remove(mRefresh);
        getContext().getContentResolver().unregisterContentObserver(mObserver);
        super.onPause();
    }
    private void refresh() {
        if (!isAdded()) return;
        try {
            boolean desktop = Controller.enabled(getContext());
            mDesktop.setChecked(desktop);
            mDesktop.setEnabled(!Controller.mApplying);
        } catch (RuntimeException error) {
            mDesktop.setEnabled(false);
            Log.e(Controller.TAG, "Cannot read desktop mode", error);
        }
    }
    private void apply(boolean desktop) {
        Controller.apply(getContext(), desktop, getActivity().getTaskId(), mRefresh);
    }

    /** User-added QS tile, using the exact same transition as the Settings switch. */
    public static final class DesktopTileService extends android.service.quicksettings.TileService {
        private final Handler mHandler = new Handler(Looper.getMainLooper());
        private final Runnable mRefresh = this::refresh;
        private final android.database.ContentObserver mObserver =
                new android.database.ContentObserver(mHandler) {
                    @Override public void onChange(boolean selfChange) { refresh(); }
                };
        @Override public void onStartListening() {
            super.onStartListening();
            Controller.restoreExternalDefault(this);
            Controller.LISTENERS.add(mRefresh);
            getContentResolver().registerContentObserver(
                    Settings.Global.getUriFor(Controller.ENABLED), false, mObserver);
            refresh();
        }
        @Override public void onStopListening() {
            Controller.LISTENERS.remove(mRefresh);
            getContentResolver().unregisterContentObserver(mObserver);
            super.onStopListening();
        }
        @Override public void onDestroy() {
            Controller.LISTENERS.remove(mRefresh);
            getContentResolver().unregisterContentObserver(mObserver);
            super.onDestroy();
        }
        @Override public void onClick() {
            super.onClick();
            Runnable toggle = () -> {
                try {
                    if (Controller.mApplying) return;
                    boolean desired = !Controller.enabled(this);
                    int taskId = -1;
                    for (ActivityManager.RunningTaskInfo task :
                            ActivityTaskManager.getInstance().getTasks(20, false, false, 0)) {
                        if (task.getActivityType() == WindowConfiguration.ACTIVITY_TYPE_STANDARD
                                && task.isVisible && task.baseActivity != null
                                && !"com.android.systemui".equals(task.baseActivity.getPackageName())) {
                            taskId = task.taskId; break;
                        }
                    }
                    Controller.apply(this, desired, taskId, mRefresh);
                } catch (RuntimeException error) {
                    Log.e(Controller.TAG, "Cannot toggle desktop mode", error);
                    refresh();
                }
            };
            if (isLocked()) unlockAndRun(toggle);
            else toggle.run();
        }
        private void refresh() {
            android.service.quicksettings.Tile tile = getQsTile();
            if (tile == null) return;
            tile.setLabel(getString(R.string.sheng_desktop_title));
            tile.setIcon(android.graphics.drawable.Icon.createWithResource(this,
                    R.drawable.tile_icon_desktop_mode));
            try {
                tile.setState(Controller.enabled(this) ? android.service.quicksettings.Tile.STATE_ACTIVE
                        : android.service.quicksettings.Tile.STATE_INACTIVE);
            } catch (RuntimeException error) {
                tile.setState(android.service.quicksettings.Tile.STATE_UNAVAILABLE);
            }
            tile.updateTile();
        }
    }

    private static final class Controller {
    private static final String TAG = "ShengDesktopMode";
    private static final String EXTERNAL = "force_desktop_mode_on_external_displays";
    private static final String EXTERNAL_CHOICE = "sheng_desktop_external_only";
    private static final ExecutorService WORKER = Executors.newSingleThreadExecutor();
    private static final Handler mHandler = new Handler(Looper.getMainLooper());
    private static boolean mApplying;
    private static final java.util.Set<Runnable> LISTENERS = new java.util.HashSet<>();
    private static final String ENABLED = "sheng_desktop_enabled";
    static boolean enabled(android.content.Context context) {
        return Settings.Global.getInt(context.getContentResolver(), ENABLED, 0) == 1;
    }
    private static void changed(android.content.Context context) {
        for (Runnable listener : new ArrayList<>(LISTENERS)) listener.run();
        android.service.quicksettings.TileService.requestListeningState(context,
                new android.content.ComponentName(context, DesktopTileService.class));
    }
    // The modern display policy defaults to an extended desktop. Undo only the
    // old page's owned overrides when migrating from its two-switch version.
    static void restoreExternalDefault(android.content.Context context) {
        ContentResolver resolver = context.getContentResolver();
        if (Settings.Global.getString(resolver, EXTERNAL_CHOICE) != null) {
            Settings.Secure.putString(resolver, Settings.Secure.MIRROR_BUILT_IN_DISPLAY, null);
            Settings.Global.putString(resolver, EXTERNAL, null);
            Settings.Global.putString(resolver, EXTERNAL_CHOICE, null);
        }
    }

    static void apply(android.content.Context supplied, boolean desktop, int settingsTask,
            Runnable complete) {
        if (mApplying) { complete.run(); return; }
        final android.content.Context context = supplied.getApplicationContext();
        final IWindowManager wm = WindowManagerGlobal.getWindowManagerService();
        final int oldMode;
        final String oldEnabled = Settings.Global.getString(context.getContentResolver(), ENABLED);
        try {
            oldMode = wm.getWindowingMode(Display.DEFAULT_DISPLAY);
        } catch (RemoteException | RuntimeException error) {
            Toast.makeText(context, R.string.sheng_desktop_failed, Toast.LENGTH_LONG).show();
            complete.run(); return;
        }
        mApplying = true;
        if (!Settings.Global.putInt(context.getContentResolver(), ENABLED, desktop ? 1 : 0)) {
            mApplying = false;
            complete.run();
            return;
        }
        changed(context);
        WORKER.execute(() -> {
            try {
                int requested = desktop ? WindowConfiguration.WINDOWING_MODE_FREEFORM
                        : WindowConfiguration.WINDOWING_MODE_FULLSCREEN;
                // Exit desktop-first policy BEFORE removing its tasks. Otherwise
                // Shell keeps an active launch root even after the last app leaves,
                // and later launches unexpectedly re-enter desktop mode.
                wm.setWindowingMode(Display.DEFAULT_DISPLAY, requested);
                if (desktop) {
                    if (settingsTask >= 0) enterDesktopTask(context, settingsTask);
                } else {
                    leaveDesktopTasks(context, settingsTask);
                }
                if (wm.getWindowingMode(Display.DEFAULT_DISPLAY) != requested) {
                    throw new IllegalStateException("WindowManager did not retain requested mode");
                }
            } catch (RemoteException | RuntimeException | IOException error) {
                Log.e(TAG, "Desktop change failed; restoring display mode", error);
                Settings.Global.putString(context.getContentResolver(), ENABLED, oldEnabled);
                try { wm.setWindowingMode(Display.DEFAULT_DISPLAY, oldMode); }
                catch (RemoteException | RuntimeException rollbackError) {
                    Log.e(TAG, "Could not restore display mode", rollbackError);
                }
                mHandler.post(() -> Toast.makeText(context,
                        R.string.sheng_desktop_failed, Toast.LENGTH_LONG).show());
            } finally {
                mHandler.post(() -> {
                    mApplying = false;
                    changed(context);
                    complete.run();
                });
            }
        });
    }

    // Android 17's multi-desk Shell owns the task hierarchy. Changing only the
    // display mode leaves a full-screen task outside the desktop. Use the same
    // pinned Shell entry points used by its own desktop tools, through Binder
    // (no root process, shell execution, fixed task IDs, or arbitrary arguments).
    private static void enterDesktopTask(android.content.Context context, int taskId)
            throws RemoteException, IOException {
        int desk = Integer.MAX_VALUE;
        // A desk has a paired minimized-task root with the same windowing mode.
        // Root-task type alone cannot identify it. Accept only IDs explicitly
        // registered as DESK by the pinned Shell repository, and still present in WM.
        String state = runDesktopShell(context, "dump");
        Matcher desks = Pattern.compile(
                "Desk ID=\\s*(\\d+), Desk Display ID=0,[^\\r\\n]*Type=DESK")
                .matcher(state);
        List<ActivityTaskManager.RootTaskInfo> roots = ActivityTaskManager.getService()
                .getAllRootTaskInfosOnDisplay(Display.DEFAULT_DISPLAY);
        while (desks.find()) {
            int candidate = Integer.parseInt(desks.group(1));
            for (ActivityTaskManager.RootTaskInfo info : roots) {
                if (info.taskId == candidate) desk = Math.min(desk, candidate);
            }
        }
        if (desk == Integer.MAX_VALUE) throw new IllegalStateException("No desktop workspace");
        desktopAction(context, "moveTaskToDesk", taskId, desk);
        awaitTaskMode(taskId, WindowConfiguration.WINDOWING_MODE_FREEFORM);
    }

    private static void leaveDesktopTasks(android.content.Context context, int settingsTask)
            throws IOException {
        List<ActivityManager.RunningTaskInfo> tasks = new ArrayList<>(
                ActivityTaskManager.getInstance().getTasks(100, false, false,
                        Display.DEFAULT_DISPLAY));
        // Bring Settings back last, keeping the page in front as apps return to tablet mode.
        tasks.sort(Comparator.comparingInt(task -> task.taskId == settingsTask ? 1 : 0));
        for (ActivityManager.RunningTaskInfo task : tasks) {
            if (task.baseActivity != null
                    && "com.android.systemui".equals(task.baseActivity.getPackageName())) continue;
            if (task.getActivityType() == WindowConfiguration.ACTIVITY_TYPE_STANDARD
                    && task.getWindowingMode() == WindowConfiguration.WINDOWING_MODE_FREEFORM) {
                desktopAction(context, "moveTaskOutOfDesk", task.taskId, -1);
                awaitTaskMode(task.taskId, WindowConfiguration.WINDOWING_MODE_FULLSCREEN);
            }
        }
    }

    private static void desktopAction(android.content.Context context, String action,
            int taskId, int deskId) throws IOException {
        if (deskId >= 0) {
            runDesktopShell(context, action, Integer.toString(taskId), Integer.toString(deskId));
        } else {
            runDesktopShell(context, action, Integer.toString(taskId));
        }
    }

    private static String runDesktopShell(android.content.Context context, String... commands)
            throws IOException {
        File output = File.createTempFile("desktop-transition-", ".txt", context.getCacheDir());
        try (FileOutputStream stream = new FileOutputStream(output)) {
            List<String> args = new ArrayList<>(List.of("service",
                    "com.android.systemui/.SystemUIService", "WMShell"));
            if (!commands[0].equals("dump")) args.add("desktopmode");
            args.addAll(List.of(commands));
            if (!Debug.dumpService("activity", stream.getFD(), args.toArray(new String[0]))) {
                throw new IllegalStateException("Desktop service unavailable");
            }
            return Files.readString(output.toPath());
        } finally {
            output.delete();
        }
    }

    private static void awaitTaskMode(int taskId, int mode) {
        for (int retry = 0; retry < 40; retry++) {
            for (ActivityManager.RunningTaskInfo task :
                    ActivityTaskManager.getInstance().getTasks(100)) {
                if (task.taskId == taskId && task.getWindowingMode() == mode) return;
            }
            SystemClock.sleep(50);
        }
        throw new IllegalStateException("Desktop task transition did not complete");
    }
    }
}
