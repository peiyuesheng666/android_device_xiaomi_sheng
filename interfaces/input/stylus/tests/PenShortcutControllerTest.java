package org.lineageos.sheng.stylus;

import android.app.ActivityManager;
import android.app.ActivityTaskManager;
import android.app.KeyguardManager;
import android.content.Context;
import android.hardware.input.InputManager;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.InputEventReceiver;
import android.view.MotionEvent;
import android.view.WindowManager;
import com.android.internal.util.ScreenshotHelper;
import java.util.ArrayList;
import java.util.Arrays;
import org.lineageos.sheng.pen.controls.PenControls.Action;
import org.lineageos.sheng.pen.controls.PenControls.Gesture;
import org.lineageos.sheng.pen.controls.PenControlsSettings;
import org.lineageos.sheng.pen.controls.PenAppOverrides;
import org.lineageos.sheng.pen.controls.PenMenuEntry;

public final class PenShortcutControllerTest {
    private static int checks;
    private static void check(boolean condition, String message) {
        checks++;
        if (!condition) throw new AssertionError(message);
    }
    private static final class Run {
        final Context context = new Context();
        final InputManager input = new InputManager();
        final WindowManager windows = new WindowManager();
        final KeyguardManager keyguard = new KeyguardManager();
        final PowerManager power = new PowerManager();
        final ArrayList<Boolean> pointer = new ArrayList<>();
        final ArrayList<Boolean> buttons = new ArrayList<>();
        final ArrayList<Integer> haptics = new ArrayList<>();
        final PenShortcutController controller;
        final InputEventReceiver receiver;
        Run(PenModel model) {
            Handler.reset(); ActivityManager.user = 0; ScreenshotHelper.screenshots = 0;
            PenControlsSettings.actions.clear(); PenShortcutMenu.latest = null;
            PenControlsSettings.vibrationLevel = 3;
            PenControlsSettings.selectedApps = null;
            ActivityTaskManager.service.focused = null;
            ActivityTaskManager.service.listener = null;
            ActivityTaskManager.service.fail = false;
            context.services.put(InputManager.class, input); context.services.put(WindowManager.class, windows);
            context.services.put(PowerManager.class, power); context.services.put(KeyguardManager.class, keyguard);
            controller = new PenShortcutController(context, new Handler(new Looper()), haptics::add, pointer::add, buttons::add);
            controller.setModel(model); controller.setAvailable(true); Handler.flushMain();
            controller.setPointerIdentity(model == PenModel.PRO ? 0x5081 : 0x4d80, "11:22:33:44:55:66");
            receiver = InputEventReceiver.latest;
        }
        void key(int usage) { controller.report(new byte[]{(byte) usage}); Handler.flushMain(); }
        void select(Action action) { PenShortcutMenu.latest.selected.accept(PenMenuEntry.operation(action)); }
        void focus(String name) {
            ActivityTaskManager.RootTaskInfo info = new ActivityTaskManager.RootTaskInfo();
            info.topActivity = new android.content.ComponentName(name, "PaintActivity");
            ActivityTaskManager.service.focused = info;
            ActivityTaskManager.service.listener.onTaskFocusChanged(1, true);
            Handler.flushMain();
        }
        MotionEvent mouse(float horizontal, float vertical) {
            MotionEvent event = new MotionEvent();
            event.source = InputDevice.SOURCE_MOUSE; event.action = MotionEvent.ACTION_HOVER_MOVE;
            event.rawX = horizontal; event.rawY = vertical;
            event.device.vendor = 34; event.device.product = 0x5081;
            event.device.address = "11:22:33:44:55:66";
            receiver.onInputEvent(event);
            return event;
        }
        void close() {
            controller.close(); Handler.flushMain();
            check(windows.attached == null && receiver.disposed && input.monitor.disposed, "close releases resources");
        }
    }
    private static void ordinary() {
        Run run = new Run(PenModel.FOCUS);
        run.key(0x4b); run.key(0x4b);
        check(ScreenshotHelper.screenshots == 1, "ordinary screenshot immediate, repeats ignored");
        run.key(0); run.key(0x4e);
        check(PenShortcutMenu.latest.visible, "ordinary menu immediate");
        run.key(0); run.key(0x6e);
        check(run.pointer.equals(Arrays.asList(true)), "third key enables native mouse even without screen hover");
        check(!PenShortcutMenu.latest.visible && run.windows.attached == null, "no red overlay or open menu");
        run.key(0x6e); check(run.pointer.size() == 1, "repeat does not toggle pointer");
        run.key(0); check(run.pointer.equals(Arrays.asList(true, false)), "ordinary release disables mouse");
        run.key(0x6e); Handler.advanceAll(8000);
        check(run.pointer.equals(Arrays.asList(true, false, true, false)), "missing release times out safely");
        check(run.input.injected == 0, "pointer mode never fabricates movement, clicks or plus keys");
        PenControlsSettings.actions.put(Gesture.DOUBLE_TAP, Action.SCREENSHOT);
        PenControlsSettings.actions.put(Gesture.SLIDE_UP, Action.SCREENSHOT);
        PenControlsSettings.actions.put(Gesture.SLIDE_DOWN, Action.SCREENSHOT);
        for (int usage : new int[]{0x58, 0x5b, 0x61}) { run.key(usage); run.key(0); }
        check(ScreenshotHelper.screenshots == 1, "ordinary pen ignores Pro-only barrel gestures");
        run.close();
    }
    private static void proMenuAndCustomization() {
        Run run = new Run(PenModel.PRO);
        run.key(0x4b); Handler.advanceAll(100); run.key(0);
        check(ScreenshotHelper.screenshots == 0, "Pro short press remains suppressed");
        run.key(0x4b); Handler.advanceAll(380);
        check(ScreenshotHelper.screenshots == 1, "Pro screenshot long press retained");
        run.key(0); run.key(0x6e); run.key(0);
        check(PenShortcutMenu.latest.visible && run.pointer.isEmpty(), "Pro squeeze defaults to menu, not mouse");
        check(Arrays.stream(PenShortcutMenu.latest.entries).anyMatch(entry -> entry.action == Action.LASER), "mouse is in default menu");
        run.select(Action.LASER); Handler.advanceAll(9000);
        check(run.pointer.equals(Arrays.asList(true)), "Pro menu mouse mode survives key release and idle interval");
        run.select(Action.LASER);
        check(run.pointer.equals(Arrays.asList(true, false)), "second menu selection exits mouse mode");
        for (int usage : new int[]{0x58, 0x5b, 0x61}) { run.key(usage); run.key(0); }
        check(ScreenshotHelper.screenshots == 1 && run.input.injected == 2,
                "slides scroll by default, unconfigured double tap does nothing");
        PenControlsSettings.actions.put(Gesture.DOUBLE_TAP, Action.SCREENSHOT);
        PenControlsSettings.actions.put(Gesture.SLIDE_UP, Action.MENU);
        PenControlsSettings.actions.put(Gesture.SLIDE_DOWN, Action.SCREENSHOT);
        run.key(0x58); run.key(0x58);
        check(ScreenshotHelper.screenshots == 2, "custom double tap executes once without physical-button hold");
        run.key(0); run.key(0x61);
        MotionEvent scroll = (MotionEvent) run.input.last;
        check(!PenShortcutMenu.latest.visible && scroll.action == MotionEvent.ACTION_SCROLL
                && scroll.coordinates.scroll > 0, "barrel slide up ignores old menu customization and scrolls up");
        run.key(0); run.select(Action.LASER); run.key(0x5b);
        scroll = (MotionEvent) run.input.last;
        check(ScreenshotHelper.screenshots == 2 && run.pointer.get(run.pointer.size() - 1)
                && scroll.coordinates.scroll < 0,
                "barrel slide down ignores old screenshot customization without exiting mouse mode");
        check(run.pointer.get(run.pointer.size() - 2), "scroll requests firmware mouse resynchronization without disabling it");
        run.key(0); run.key(0x6e); run.key(0);
        check(!PenShortcutMenu.latest.visible && run.pointer.get(run.pointer.size() - 1),
                "mouse squeeze does not reopen shortcut menu or exit pointer mode");
        run.key(0x58); run.key(0x58); run.key(0);
        check(!run.pointer.get(run.pointer.size() - 1) && ScreenshotHelper.screenshots == 2,
                "mouse double tap exits mode instead of executing customized action");
        run.key(0x58); run.key(0);
        check(ScreenshotHelper.screenshots == 3, "double tap customization resumes outside mouse mode");
        run.key(0); run.key(0x4b); Handler.advanceAll(380);
        check(ScreenshotHelper.screenshots == 4, "barrel customization preserves physical side-button action");
        run.close();
    }
    private static void proMouseClickAndDrag() {
        Run run = new Run(PenModel.PRO);
        run.key(0x6e); run.key(0); run.select(Action.LASER);
        int hapticsBeforeMouse = run.haptics.size();
        check(hapticsBeforeMouse > 0, "normal Pro squeeze feedback remains enabled outside mouse mode");
        run.mouse(300, 200); run.key(0x6e); run.key(0x6e);
        check(run.buttons.equals(Arrays.asList(true)), "squeeze requests native primary down once despite repeats");
        run.mouse(450, 260);
        check(run.input.injected == 0 && run.buttons.equals(Arrays.asList(true)),
                "native device owns drag movement without a conflicting injected mouse");
        MotionEvent foreign = run.mouse(450, 260);
        foreign.device.address = "22:33:44:55:66:77";
        int before = run.input.injected;
        run.receiver.onInputEvent(foreign);
        check(run.input.injected == before, "another Bluetooth mouse cannot control the pen drag");
        run.key(0);
        check(run.buttons.equals(Arrays.asList(true, false)), "squeeze release finishes native click or drag");
        check(run.haptics.size() == hapticsBeforeMouse, "mouse squeeze and release do not send accessory vibration commands");
        run.key(0x6e); Handler.advanceAll(8000);
        check(run.buttons.equals(Arrays.asList(true, false, true, false))
                && run.pointer.get(run.pointer.size() - 1), "stale held primary releases without disabling Pro movement");
        run.key(0);
        run.mouse(500, 300); run.key(0x6e);
        run.controller.setAvailable(false); Handler.flushMain();
        check(run.buttons.equals(Arrays.asList(true, false, true, false, true, false))
                && !run.pointer.get(run.pointer.size() - 1), "availability loss releases native mouse safely");
        run.close();
    }
    private static void proRepeatedMouseSqueezes() {
        Run run = new Run(PenModel.PRO);
        run.key(0x6e); run.key(0); run.select(Action.LASER);
        int hapticsBeforeMouse = run.haptics.size();
        for (int cycle = 0; cycle < 20; cycle++) {
            run.mouse(300 + cycle, 200);
            run.key(0x6e);
            run.mouse(301 + cycle, 201);
            run.key(0);
            check(run.buttons.size() == (cycle + 1) * 2
                    && run.buttons.get(cycle * 2) && !run.buttons.get(cycle * 2 + 1),
                    "repeated mouse squeeze retains distinct native press and release");
        }
        check(run.haptics.size() == hapticsBeforeMouse && run.pointer.equals(Arrays.asList(true)),
                "twenty squeezes neither send vibration commands nor exit mouse mode");
        run.key(0x58); run.key(0);
        check(run.pointer.equals(Arrays.asList(true, false)), "double tap still exits after repeated squeezes");
        run.key(0x6e); run.key(0);
        check(run.haptics.size() > hapticsBeforeMouse && PenShortcutMenu.latest.visible,
                "normal menu and squeeze feedback return after pointer exit");
        run.close();
    }
    private static void lifecycle() {
        Run run = new Run(PenModel.FOCUS);
        run.controller.report(new byte[]{0x6e}); run.controller.setAvailable(false); run.controller.setAvailable(true);
        Handler.flushMain(); check(run.pointer.isEmpty(), "queued stale-generation press cannot enable mouse");
        run.key(0x6e); run.controller.setAvailable(false); Handler.flushMain();
        check(run.pointer.equals(Arrays.asList(true, false)), "native pause stops mouse");
        run.controller.setAvailable(true); run.key(0x6e);
        run.controller.report(new byte[0]); Handler.flushMain();
        check(!run.pointer.get(run.pointer.size() - 1), "malformed keyboard report cancels mode");
        run.key(0x6e); run.keyguard.locked = true; run.controller.setAvailable(true); Handler.flushMain();
        check(!run.pointer.get(run.pointer.size() - 1), "availability refresh detects keyguard and stops mouse");
        int before = run.pointer.size(); run.key(0x6e);
        check(run.pointer.size() == before, "locked device cannot enter mouse mode");
        run.keyguard.locked = false; run.controller.setAvailable(true); run.key(0x6e);
        run.close(); check(!run.pointer.get(run.pointer.size() - 1), "close exits mouse mode");
        Handler.advanceAll(10000); check(run.windows.attached == null, "no late overlay");
    }
    public static void main(String[] arguments) {
        ordinary(); proMenuAndCustomization(); proMouseClickAndDrag(); proRepeatedMouseSqueezes(); lifecycle();
        appOverrides();
        appOverrideBoundaries();
        System.out.println("PASS shortcut_controller_checks=" + checks + " android_services=host_doubles hardware_tested=false");
    }
    private static void appOverrides() {
        check(PenAppOverrides.read(" net.huanci.hsjpro,net.huanci.hsjpro,*,bad/package,com.example.draw ").size() == 2,
                "app list validates exact package names and removes duplicates");
        for (PenModel model : new PenModel[]{PenModel.PRO, PenModel.FOCUS}) {
            Run run = new Run(model);
            PenControlsSettings.selectedApps = "net.huanci.hsjpro,com.example.other";
            run.focus("net.huanci.hsjpro");
            int usage = model == PenModel.PRO ? 0x6e : 0x4e;
            run.key(usage); run.key(usage);
            check(run.input.events.size() == 1 && ((KeyEvent)run.input.last).code == KeyEvent.KEYCODE_F1
                    && ((KeyEvent)run.input.last).action == KeyEvent.ACTION_DOWN,
                    "selected app receives immediate primary down without hold delay or repeats");
            run.key(0);
            check(run.input.events.size() == 2 && ((KeyEvent)run.input.last).action == KeyEvent.ACTION_UP,
                    "selected app receives matching release");
            check(run.input.targetUids.stream().allMatch(uid -> uid == 12345)
                    && ((KeyEvent)run.input.last).source == InputDevice.SOURCE_STYLUS,
                    "button events target only the focused app UID with stylus source");
            check(ScreenshotHelper.screenshots == 0 && PenShortcutMenu.latest == null && run.pointer.isEmpty()
                    && run.haptics.isEmpty(), "takeover never runs global actions, pointer or feedback");
            run.key(0x4b); run.key(0);
            check(((KeyEvent)run.input.last).code == KeyEvent.KEYCODE_F2, "ordinary and Pro secondary keys remain distinct");
            if (model == PenModel.FOCUS) {
                run.key(0x6e); run.key(0);
                check(((KeyEvent)run.input.last).code == KeyEvent.KEYCODE_F3 && run.pointer.isEmpty(), "ordinary third key is an app key, not mouse mode");
            } else {
                run.key(0x58); run.key(0);
                check(((KeyEvent)run.input.last).code == KeyEvent.KEYCODE_F2 && ((KeyEvent)run.input.last).action == KeyEvent.ACTION_UP,
                        "Pro double tap passes an app gesture key pair without global action");
                run.key(0x61); run.key(0);
                check(((KeyEvent)run.input.last).code == 92, "Pro up gesture passes a page key instead of global scrolling");
                run.key(0x5b); run.key(0);
                check(((KeyEvent)run.input.last).code == 93, "Pro down gesture passes a distinct page key");
            }
            run.key(usage); run.focus("com.example.other");
            KeyEvent cancelled = (KeyEvent)run.input.last;
            check(cancelled.action == KeyEvent.ACTION_UP && (cancelled.flags & KeyEvent.FLAG_CANCELED) != 0,
                    "focus change cancels held key rather than leaking it to a new app");
            int before = run.input.events.size();
            run.key(usage);
            check(run.input.events.size() == before, "held button cannot start a new action in another app");
            run.key(0); run.key(usage); Handler.advanceAll(8000);
            check((((KeyEvent)run.input.last).flags & KeyEvent.FLAG_CANCELED) != 0, "missing release cancels after timeout");
            run.key(0); run.focus("com.example.launcher");
            Handler.advanceAll(0);
            run.key(0x4b); if (model == PenModel.PRO) Handler.advanceAll(380);
            check(ScreenshotHelper.screenshots == 1, "leaving selected apps restores original global shortcuts");
            run.key(0); run.close();
            check(ActivityTaskManager.service.listener == null && run.context.resolver.observer == null,
                    "closing the session unregisters app and preference listeners");
        }
    }
    private static void appOverrideBoundaries() {
        Run run = new Run(PenModel.PRO);
        run.key(0x6e); run.key(0); run.select(Action.LASER); run.key(0x6e);
        check(run.buttons.equals(Arrays.asList(true)), "mouse drag is active before app takeover");
        PenControlsSettings.selectedApps = "net.huanci.hsjpro";
        run.focus("net.huanci.hsjpro");
        check(run.buttons.equals(Arrays.asList(true, false)) && !run.pointer.get(run.pointer.size() - 1)
                && !PenShortcutMenu.latest.visible, "entering selected app releases drag and closes mouse/menu immediately");
        run.key(0); run.key(0x6e);
        check(((KeyEvent)run.input.last).code == KeyEvent.KEYCODE_F1, "app takeover continues after cancelling global drag");
        run.keyguard.locked = true; run.controller.setAvailable(true); Handler.flushMain();
        check((((KeyEvent)run.input.last).flags & KeyEvent.FLAG_CANCELED) != 0, "lock screen cancels held app key");
        int before = run.input.events.size(); run.key(0x6e);
        check(run.input.events.size() == before, "locked device never forwards app keys");
        run.close();

        run = new Run(PenModel.FOCUS);
        PenControlsSettings.selectedApps = "net.huanci.hsjpro";
        run.focus("net.huanci.hsjpro");
        run.controller.report(new byte[]{0x4e});
        ActivityTaskManager.service.focused.topActivity = new android.content.ComponentName("com.example.launcher", "Main");
        Handler.flushMain();
        check(run.input.events.isEmpty() && ScreenshotHelper.screenshots == 0 && PenShortcutMenu.latest == null,
                "focus change between decoding and dispatch cannot redirect a key or execute global fallback");
        run.key(0); run.focus("net.huanci.hsjpro");
        run.key(0x4e); run.controller.report(new byte[]{1, 2, 3}); Handler.flushMain();
        check((((KeyEvent)run.input.last).flags & KeyEvent.FLAG_CANCELED) != 0,
                "non-key reports never become app shortcuts and cancel stale app press");
        run.key(0); ActivityTaskManager.service.fail = true;
        before = run.input.events.size(); run.key(0x4b); run.key(0);
        check(run.input.events.size() == before && ScreenshotHelper.screenshots == 0 && run.pointer.isEmpty(),
                "foreground lookup failure suppresses global shortcuts without untargeted injection");
        ActivityTaskManager.service.fail = false; run.focus("net.huanci.hsjpro");
        run.input.rejectTarget = true; run.key(0x4e);
        check(ScreenshotHelper.screenshots == 0 && PenShortcutMenu.latest == null,
                "failed app injection never falls back to a system shortcut");
        run.input.rejectTarget = false; run.key(0);
        PenControlsSettings.selectedApps = ""; run.context.resolver.observer.onChange(false);
        Handler.advanceAll(0); run.key(0x4b);
        check(ScreenshotHelper.screenshots == 1, "removing app preference restores shortcuts without reconnecting pen");
        run.key(0); run.close();

        run = new Run(PenModel.PRO);
        run.controller.report(new byte[]{0x6e});
        PenControlsSettings.selectedApps = "net.huanci.hsjpro";
        ActivityTaskManager.RootTaskInfo focused = new ActivityTaskManager.RootTaskInfo();
        focused.topActivity = new android.content.ComponentName("net.huanci.hsjpro", "PaintActivity");
        ActivityTaskManager.service.focused = focused; Handler.flushMain();
        check(PenShortcutMenu.latest == null && run.pointer.isEmpty(),
                "queued global gesture rechecks focused app before executing");
        run.close();
    }
}
