package org.lineageos.sheng.stylus;

import android.app.ActivityTaskManager;
import android.app.TaskStackListener;
import android.content.Context;
import android.content.pm.PackageManager;
import android.database.ContentObserver;
import android.hardware.input.InputManager;
import android.os.Handler;
import android.os.RemoteException;
import android.os.SystemClock;
import android.provider.Settings;
import android.util.Log;
import android.view.Display;
import android.view.InputDevice;
import android.view.KeyCharacterMap;
import android.view.KeyEvent;
import java.util.Set;
import java.util.function.BooleanSupplier;
import org.lineageos.sheng.pen.controls.PenAppOverrides;
import org.lineageos.sheng.pen.controls.PenControls;
import org.lineageos.sheng.pen.controls.PenControlsSettings;

final class PenAppRouting {
    private static final String TAG = "ShengPenAppRouting";
    private static final Target UNRESOLVED = new Target("unavailable", -1);
    private final Context context;
    private final Handler main;
    private final int user;
    private final BooleanSupplier available;
    private final Runnable cancelGlobal;
    private final ContentObserver preferences;
    private final TaskStackListener tasks;
    private final Runnable timeout = () -> cancel();
    private final Runnable fallback = new Runnable() {
        @Override public void run() {
            if (closed) return;
            refresh();
            main.postDelayed(this, 500);
        }
    };
    private volatile boolean blocked, closed;
    private boolean registeredTasks, registeredPreferences, pro, waitForRelease;
    private Target target;
    private int usage, pressedCode;
    private long downTime;

    private static final class Target {
        final String name;
        final int uid;
        Target(String name, int uid) { this.name = name; this.uid = uid; }
        boolean same(Target other) { return other != null && uid == other.uid && name.equals(other.name); }
    }

    PenAppRouting(Context context, Handler main, int user, BooleanSupplier available, Runnable cancelGlobal) {
        this.context = context; this.main = main; this.user = user;
        this.available = available; this.cancelGlobal = cancelGlobal;
        preferences = new ContentObserver(main) {
            @Override public void onChange(boolean selfChange) { refresh(); }
        };
        tasks = new TaskStackListener() {
            @Override public void onTaskStackChanged() { main.post(PenAppRouting.this::refresh); }
            @Override public void onTaskFocusChanged(int taskId, boolean focused) { main.post(PenAppRouting.this::refresh); }
        };
        main.post(this::start);
    }

    void setModel(PenModel model) { main.post(() -> pro = model == PenModel.PRO); }
    boolean blocked() { return blocked; }

    private void start() {
        if (closed) return;
        try {
            context.getContentResolver().registerContentObserver(Settings.Secure.getUriFor(PenControls.APP_OVERRIDES),
                    false, preferences, user);
            registeredPreferences = true;
            ActivityTaskManager.getService().registerTaskStackListener(tasks);
            registeredTasks = true;
        } catch (RemoteException | RuntimeException error) {
            Log.w(TAG, "App routing observer unavailable; using foreground checks", error);
            main.post(fallback);
        }
        refresh();
    }

    private Target resolve() {
        if (closed || !available.getAsBoolean()) return null;
        Set<String> selected = PenAppOverrides.read(PenControlsSettings.read(context, PenControls.APP_OVERRIDES, user));
        if (selected.isEmpty()) return null;
        try {
            ActivityTaskManager.RootTaskInfo info = ActivityTaskManager.getService().getFocusedRootTaskInfo();
            if (info == null || info.topActivity == null) return UNRESOLVED;
            if (info.userId != user || info.displayId != Display.DEFAULT_DISPLAY) return UNRESOLVED;
            String name = info.topActivity.getPackageName();
            if (!selected.contains(name)) return null;
            int uid = context.getPackageManager().getApplicationInfoAsUser(name, 0, user).uid;
            return new Target(name, uid);
        } catch (RemoteException | PackageManager.NameNotFoundException | RuntimeException error) {
            Log.w(TAG, "Focused app unavailable", error);
            return UNRESOLVED;
        }
    }

    boolean intercept(byte[] report) {
        if (closed) return false;
        Target expected = resolve();
        if (expected == null && !blocked) return false;
        byte[] snapshot = report == null ? null : report.clone();
        main.post(() -> {
            if (closed) return;
            refresh();
            if (target != null && target.same(expected)) accept(snapshot);
            else if (snapshot != null && snapshot.length == 1 && snapshot[0] != 0) waitForRelease = true;
        });
        return true;
    }

    boolean suppressGlobal() {
        refresh();
        return blocked;
    }

    private void refresh() {
        if (closed) return;
        Target next = resolve();
        if (target == null && next == null || target != null && target.same(next)) return;
        cancel();
        target = next;
        blocked = next != null;
        cancelGlobal.run();
        Log.i(TAG, "app=" + (next == null ? "none" : next.name) + " takeover=" + blocked);
    }

    private void accept(byte[] report) {
        if (report == null || report.length != 1) { cancel(); return; }
        int next = report[0] & 255;
        if (next == 0) {
            release(false); usage = 0; waitForRelease = false;
            return;
        }
        if (waitForRelease || next == usage) return;
        release(false);
        usage = next;
        int code = keyCode(next, pro);
        if (code == KeyEvent.KEYCODE_UNKNOWN) return;
        downTime = SystemClock.uptimeMillis();
        pressedCode = code;
        if (!send(KeyEvent.ACTION_DOWN, false)) {
            release(true); waitForRelease = true; return;
        }
        if (next == 0x58 || next == 0x61 || next == 0x5b) release(false);
        else main.postDelayed(timeout, 8000);
    }

    static int keyCode(int usage, boolean pro) {
        switch (usage) {
            case 0x4e: return KeyEvent.KEYCODE_F1;
            case 0x4b: return KeyEvent.KEYCODE_F2;
            case 0x6e: return pro ? KeyEvent.KEYCODE_F1 : KeyEvent.KEYCODE_F3;
            case 0x58: return pro ? KeyEvent.KEYCODE_F2 : KeyEvent.KEYCODE_UNKNOWN;
            case 0x61: return pro ? KeyEvent.KEYCODE_PAGE_UP : KeyEvent.KEYCODE_UNKNOWN;
            case 0x5b: return pro ? KeyEvent.KEYCODE_PAGE_DOWN : KeyEvent.KEYCODE_UNKNOWN;
            default: return KeyEvent.KEYCODE_UNKNOWN;
        }
    }

    private boolean send(int action, boolean cancelled) {
        if (target == null || target.uid < 0 || pressedCode == 0) return false;
        KeyEvent event = new KeyEvent(downTime, SystemClock.uptimeMillis(), action, pressedCode, 0, 0,
                KeyCharacterMap.VIRTUAL_KEYBOARD, 0, KeyEvent.FLAG_FROM_SYSTEM | (cancelled ? KeyEvent.FLAG_CANCELED : 0),
                InputDevice.SOURCE_STYLUS);
        event.setDisplayId(Display.DEFAULT_DISPLAY);
        try {
            return context.getSystemService(InputManager.class).injectInputEvent(event,
                    InputManager.INJECT_INPUT_EVENT_MODE_ASYNC, target.uid);
        } catch (RuntimeException error) {
            Log.w(TAG, "App button unavailable", error);
            return false;
        }
    }

    private void release(boolean cancelled) {
        main.removeCallbacks(timeout);
        if (pressedCode != 0) send(KeyEvent.ACTION_UP, cancelled);
        pressedCode = 0;
    }

    void cancel() {
        release(true);
        waitForRelease = usage != 0;
    }

    void close() {
        cancel(); closed = true; blocked = false; target = null;
        main.removeCallbacks(fallback);
        if (registeredPreferences) context.getContentResolver().unregisterContentObserver(preferences);
        if (registeredTasks) try { ActivityTaskManager.getService().unregisterTaskStackListener(tasks); }
        catch (RemoteException | RuntimeException error) { Log.w(TAG, "App routing listener cleanup failed", error); }
    }
}
