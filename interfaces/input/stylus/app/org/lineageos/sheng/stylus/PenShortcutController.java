// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

import android.app.ActivityManager;
import android.app.KeyguardManager;
import android.content.Context;
import android.content.Intent;
import android.hardware.input.InputManager;
import android.media.session.MediaSessionManager;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.os.UserHandle;
import android.util.Log;
import android.view.Display;
import android.view.InputDevice;
import android.view.InputEvent;
import android.view.InputEventReceiver;
import android.view.InputMonitor;
import android.view.KeyCharacterMap;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.WindowManager;
import android.widget.Toast;
import com.android.internal.util.ScreenshotHelper;
import java.util.function.IntConsumer;
import org.lineageos.sheng.pen.controls.PenControls;
import org.lineageos.sheng.pen.controls.PenControls.Action;
import org.lineageos.sheng.pen.controls.PenControls.Gesture;
import org.lineageos.sheng.pen.controls.PenControlsSettings;
import org.lineageos.sheng.pen.controls.PenMenuEntry;
import org.lineageos.sheng.pen.controls.PenMenuApps;

/** Decoding stays on the GATT actor; windows and user actions stay on the main looper. */
final class PenShortcutController {
    private static final String TAG = "ShengPenButtons";
    private final Context context;
    private final Handler actor, main = new Handler(Looper.getMainLooper());
    private final IntConsumer feedback;
    private final PenButtonState state;
    private final int user;
    private final Runnable held;
    private final Runnable releaseTimeout;
    private volatile boolean available, closed;
    private volatile int generation;
    private PenShortcutMenu menu;
    private InputMonitor monitor;
    private InputEventReceiver receiver;
    private float hoverX = -1, hoverY = -1;
    private long hoverAt;

    PenShortcutController(Context context, Handler actor, IntConsumer feedback) {
        this.context = context; this.actor = actor; this.feedback = feedback;
        user = ActivityManager.getCurrentUser();
        state = new PenButtonState(new PenButtonState.Listener() {
            @Override public void down(Gesture gesture) {
                if (!eligible()) return;
                if (gesture.haptic != 0) vibrate(gesture.haptic);
                Action action = PenControlsSettings.action(context, gesture, user);
                final int ticket = generation;
                Log.i(TAG, "gesture=" + gesture + " action=" + action);
                main.post(() -> { if (ticket == generation && eligible()) run(action); });
            }
            @Override public void up(Gesture gesture) {
                if (gesture == Gesture.SQUEEZE && eligible()) vibrate(2);
            }
        });
        held = () -> { if (eligible()) state.held(SystemClock.uptimeMillis()); };
        releaseTimeout = () -> { state.clear(); actor.removeCallbacks(held); };
        main.post(this::startPointerObserver);
    }

    private boolean eligible() {
        return !closed && available && ActivityManager.getCurrentUser() == user
                && context.getSystemService(PowerManager.class).isInteractive()
                && !context.getSystemService(KeyguardManager.class).isKeyguardLocked();
    }
    private void vibrate(int kind) {
        if (PenControlsSettings.vibration(context, user) > 0) feedback.accept(kind);
    }
    void setAvailable(boolean enabled) {
        if (available == enabled) return;
        available = enabled;
        if (!enabled) {
            generation++; state.clear(); actor.removeCallbacks(held); actor.removeCallbacks(releaseTimeout);
            main.post(() -> { if (menu != null) menu.hide(); });
        }
    }
    void report(byte[] report) {
        if (!eligible()) { state.clear(); return; }
        boolean accepted = state.accept(report, SystemClock.uptimeMillis());
        if (!accepted) {
            actor.removeCallbacks(held); actor.removeCallbacks(releaseTimeout);
            if (report.length == 1) Log.i(TAG, "unmapped keyboard usage=0x" + Integer.toHexString(report[0] & 255));
            return;
        }
        actor.removeCallbacks(held); actor.removeCallbacks(releaseTimeout);
        long delay = state.holdDelay(SystemClock.uptimeMillis());
        if (delay >= 0) actor.postDelayed(held, delay);
        if (report[0] != 0) actor.postDelayed(releaseTimeout, 8000);
    }
    void close() {
        closed = true; generation++; available = false; state.clear();
        actor.removeCallbacks(held); actor.removeCallbacks(releaseTimeout);
        main.post(() -> {
            if (menu != null) menu.hide();
            if (receiver != null) { receiver.dispose(); receiver = null; }
            if (monitor != null) { monitor.dispose(); monitor = null; }
        });
    }

    private void startPointerObserver() {
        if (closed) return;
        try {
            monitor = context.getSystemService(InputManager.class)
                    .monitorGestureInput("Sheng pen shortcuts", Display.DEFAULT_DISPLAY);
            receiver = new InputEventReceiver(monitor.getInputChannel(), main.getLooper()) {
                @Override public void onInputEvent(InputEvent event) {
                    try {
                        if (!(event instanceof MotionEvent)) return;
                        MotionEvent motion = (MotionEvent) event;
                        InputDevice device = motion.getDevice();
                        if (device == null || !"NVTCapacitivePenP81c".equals(device.getName())
                                || !motion.isFromSource(InputDevice.SOURCE_STYLUS)
                                || motion.getDisplayId() != Display.DEFAULT_DISPLAY) return;
                        switch (motion.getActionMasked()) {
                            case MotionEvent.ACTION_HOVER_ENTER:
                            case MotionEvent.ACTION_HOVER_MOVE:
                            case MotionEvent.ACTION_MOVE:
                            case MotionEvent.ACTION_DOWN:
                                hoverX = motion.getX(); hoverY = motion.getY(); hoverAt = SystemClock.uptimeMillis();
                                break;
                            case MotionEvent.ACTION_CANCEL:
                                hoverAt = 0; break;
                        }
                    } finally { finishInputEvent(event, false); }
                }
            };
        } catch (RuntimeException error) {
            if (monitor != null) { monitor.dispose(); monitor = null; }
            Log.w(TAG, "Pointer position unavailable; menu will use screen edge", error);
        }
    }

    private void runEntry(PenMenuEntry entry) {
        if(!eligible())return;
        if(entry.action!=null){run(entry.action);return;}
        try { PenMenuApps.launch(context,entry,user); }
        catch(RuntimeException error) {
            Log.w(TAG,"Selected app unavailable",error);
            boolean zh=context.getResources().getConfiguration().getLocales().get(0).getLanguage().equals("zh");
            Toast.makeText(context,zh?"应用不可用，请在手写笔设置中重新选择":"App unavailable. Choose another in pen settings.",Toast.LENGTH_SHORT).show();
        }
    }

    private void run(Action action) {
        if (!eligible() || action == Action.NONE) return;
        try {
            switch (action) {
                case MENU:
                    if (menu == null) menu = new PenShortcutMenu(context, main, this::runEntry);
                    boolean fresh = SystemClock.uptimeMillis() - hoverAt < 1500;
                    menu.toggle(PenMenuEntry.read(PenControlsSettings.read(context, PenControls.MENU, user)),
                            fresh ? hoverX : -1, fresh ? hoverY : -1);
                    return;
                case BACK: key(KeyEvent.KEYCODE_BACK, 0); break;
                case HOME: key(KeyEvent.KEYCODE_HOME, 0); break;
                case RECENTS: key(KeyEvent.KEYCODE_APP_SWITCH, 0); break;
                case UNDO: key(KeyEvent.KEYCODE_Z, KeyEvent.META_CTRL_ON | KeyEvent.META_CTRL_LEFT_ON); break;
                case REDO: key(KeyEvent.KEYCODE_Z, KeyEvent.META_CTRL_ON | KeyEvent.META_CTRL_LEFT_ON
                        | KeyEvent.META_SHIFT_ON | KeyEvent.META_SHIFT_LEFT_ON); break;
                case MEDIA:
                    MediaSessionManager media = context.getSystemService(MediaSessionManager.class);
                    long now = SystemClock.uptimeMillis();
                    KeyEvent down = new KeyEvent(now, now, KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE, 0);
                    media.dispatchMediaKeyEvent(down, false);
                    media.dispatchMediaKeyEvent(KeyEvent.changeAction(down, KeyEvent.ACTION_UP), false);
                    break;
                case SCREENSHOT:
                    new ScreenshotHelper(context).takeScreenshot(WindowManager.TAKE_SCREENSHOT_FULLSCREEN,
                            WindowManager.ScreenshotSource.SCREENSHOT_KEY_OTHER, main, null);
                    break;
                case ASSISTANT:
                    context.startActivityAsUser(new Intent(Intent.ACTION_ASSIST).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                            UserHandle.of(user));
                    break;
                case SETTINGS:
                    context.startActivityAsUser(new Intent().setClassName("org.lineageos.sheng.pen",
                            "org.lineageos.sheng.pen.CompatibilityActivity").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                            UserHandle.of(user));
                    break;
                default: break;
            }
        } catch (RuntimeException error) {
            Log.w(TAG, "Shortcut unavailable: " + action, error);
            Toast.makeText(context, chinese() ? "此操作暂不可用" : "Action unavailable", Toast.LENGTH_SHORT).show();
        }
    }
    private void key(int code, int modifiers) {
        InputManager input = context.getSystemService(InputManager.class);
        long now = SystemClock.uptimeMillis();
        KeyEvent down = new KeyEvent(now, now, KeyEvent.ACTION_DOWN, code, 0, modifiers,
                KeyCharacterMap.VIRTUAL_KEYBOARD, 0, KeyEvent.FLAG_FROM_SYSTEM, InputDevice.SOURCE_KEYBOARD);
        input.injectInputEvent(down, InputManager.INJECT_INPUT_EVENT_MODE_ASYNC);
        input.injectInputEvent(KeyEvent.changeAction(down, KeyEvent.ACTION_UP), InputManager.INJECT_INPUT_EVENT_MODE_ASYNC);
    }
    private boolean chinese() { return context.getResources().getConfiguration().getLocales().get(0).getLanguage().equals("zh"); }
}
