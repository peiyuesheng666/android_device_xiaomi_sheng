// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.keyboard;

import android.app.Application;
import android.content.Context;
import android.content.SharedPreferences;
import android.hardware.input.InputManager;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.SystemClock;
import android.provider.Settings;
import android.util.Log;
import android.view.InputDevice;

import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Synchronizes permanent pogo HID endpoints with physical attachment and cover fold. */
public final class PresenceApplication extends Application
        implements InputManager.InputDeviceListener {
    private static final String TAG = "ShengKeyboardPresence";
    private static final String[] STATUS = {
        "/sys/class/nanodev/nanodev0/_version176x",
        "/sys/class/misc/nanodev0/connection",
    };
    private static final Pattern KEY = Pattern.compile("(?<![A-Za-z0-9_])Connected\\s*=");
    private static final Pattern VALUE = Pattern.compile("\\s*\\[\\s*([01])\\s*\\]");
    private static final long POLL_MS = 250;
    private static final long DEBOUNCE_MS = 1000;

    private Handler handler;
    private InputManager manager;
    private SharedPreferences journal;
    private InputAccess input;
    private KeyboardController controller;
    private Set<String> owned = new HashSet<>();
    private int bootCount = -1;
    private Boolean pending;
    private Boolean applied;
    private long pendingSince;
    private long nextErrorLog;
    private long firmwareGeneration = -1;
    private final Runnable poll = this::pollOnce;

    @Override public void onCreate() {
        super.onCreate();
        journal = createDeviceProtectedStorageContext()
                .getSharedPreferences("pogo_input_ownership", Context.MODE_PRIVATE);
        manager = getSystemService(InputManager.class);
        controller = new KeyboardController(this);
        HandlerThread worker = new HandlerThread("sheng-keyboard-presence");
        worker.start();
        handler = new Handler(worker.getLooper());
        KeyboardPointerReceiver.register(this, handler);
        manager.registerInputDeviceListener(this, handler);
        handler.post(poll);
    }

    static Boolean connected(String text) {
        Matcher key = KEY.matcher(text);
        if (!key.find()) return null;
        Matcher value = VALUE.matcher(text.substring(key.end()));
        if (!value.lookingAt() || key.find()) return null;
        return "1".equals(value.group(1));
    }

    static boolean pogo(InputDevice device) {
        if (device == null || device.getVendorId() != 0x15d9) return false;
        switch (device.getProductId()) {
            case 0x00a1: return "Xiaomi Touch".equals(device.getName());
            case 0x00a2: return "Xiaomi Mouse".equals(device.getName());
            case 0x00a3: return "Xiaomi Keyboard".equals(device.getName());
            case 0x00a4: return "Xiaomi Consumer".equals(device.getName());
            default: return false;
        }
    }

    private void prepareJournal() {
        if (bootCount >= 0) return;
        int currentBoot = Settings.Global.getInt(getContentResolver(), "boot_count", -1);
        if (currentBoot < 0) throw new IllegalStateException("Boot identity unavailable");
        Set<String> records = new HashSet<>(journal.getStringSet("owned", Collections.emptySet()));
        if (journal.getInt("boot_count", -1) != currentBoot) {
            // InputManager's disabled-device set does not survive a system reboot.
            records.clear();
            if (!journal.edit().putInt("boot_count", currentBoot)
                    .putStringSet("owned", records).commit()) {
                throw new IllegalStateException("Cannot reset stale ownership journal");
            }
        }
        owned = records;
        bootCount = currentBoot;
    }

    private void saveOwned(Set<String> next) {
        if (!journal.edit().putInt("boot_count", bootCount)
                .putStringSet("owned", new HashSet<>(next)).commit()) {
            throw new IllegalStateException("Cannot commit input ownership");
        }
        owned = new HashSet<>(next);
    }

    private void disableDisconnected() throws Exception {
        for (int id : input.ids()) {
            InputDevice device = input.device(id);
            if (!pogo(device) || !device.isEnabled()) continue;
            String descriptor = device.getDescriptor();
            if (descriptor == null || descriptor.isEmpty()) {
                throw new IllegalStateException("Pogo input has no stable identity");
            }
            if (!owned.contains(descriptor)) {
                Set<String> next = new HashSet<>(owned);
                next.add(descriptor);
                // Persist before the RPC: process death cannot discard a completed disable.
                saveOwned(next);
            }
            input.disable(id);
        }
    }

    private void restoreOwned() throws Exception {
        if (owned.isEmpty()) return;
        Set<String> next = new HashSet<>(owned);
        for (int id : input.ids()) {
            InputDevice device = input.device(id);
            if (!pogo(device) || !owned.contains(device.getDescriptor())) continue;
            if (device.isEnabled()) {
                next.remove(device.getDescriptor());
            } else {
                input.enable(id);
                // Keep the durable record until a later device snapshot confirms enable.
            }
        }
        if (!next.equals(owned)) saveOwned(next);
    }

    private void pollOnce() {
        try {
            prepareJournal();
            if (input == null) input = new InputAccess();
            Boolean state;
            try {
                state = null;
                for (String path : STATUS) {
                    try {
                        state = connected(new String(Files.readAllBytes(Paths.get(path)),
                                StandardCharsets.UTF_8));
                        if (state != null) break;
                    } catch (java.nio.file.NoSuchFileException missing) {
                        // The stock and source kernels expose different real state nodes.
                    }
                }
            } catch (Exception unavailable) {
                state = null;
            }
            try {
                long nextGeneration = Long.parseLong(new String(Files.readAllBytes(Paths.get(
                        "/sys/class/misc/nanodev0/firmware_generation")),
                        StandardCharsets.UTF_8).trim());
                if (nextGeneration < 0) throw new IllegalStateException("Invalid firmware generation");
                if (firmwareGeneration >= 0 && firmwareGeneration != nextGeneration) {
                    controller.firmwareReloaded();
                }
                firmwareGeneration = nextGeneration;
            } catch (java.nio.file.NoSuchFileException stockKernel) {
                // The stock transport manages its firmware lifecycle itself.
            }
            int tabletMode = input.tabletMode();
            controller.update(state, tabletMode == 0 && Settings.System.getInt(
                    getContentResolver(), "touchpad_enabled", 1) != 0,
                    Settings.Secure.getInt(getContentResolver(), KeyboardBacklight.SETTING, -1),
                    tabletMode);
            Boolean usable = state != null && !state || tabletMode == 1 ? Boolean.FALSE
                    : Boolean.TRUE.equals(state) && tabletMode == 0 ? Boolean.TRUE : null;
            if (usable == null) {
                pending = null;
                applied = null;
                restoreOwned(); // Unknown must not leave real keyboard input blocked.
                throw new IllegalStateException("Connection or fold state unavailable");
            }
            long now = SystemClock.uptimeMillis();
            if (!usable.equals(pending)) { pending = usable; pendingSince = now; }
            // A folded cover must stop delivering input promptly. Reattachment is
            // debounced before restoring the endpoints owned by this service.
            if (tabletMode == 1 || now - pendingSince >= DEBOUNCE_MS) {
                if (usable) restoreOwned(); else disableDisconnected();
                if (!usable.equals(applied)) {
                    applied = usable;
                    Log.i(TAG, "Pogo connected=" + state + " folded=" + (tabletMode == 1)
                            + " usable=" + usable);
                }
            }
        } catch (Exception error) {
            long now = SystemClock.uptimeMillis();
            if (now >= nextErrorLog) {
                Log.w(TAG, "Presence synchronization pending: " + error.getClass().getSimpleName()
                        + ": " + error.getMessage());
                nextErrorLog = now + 30000;
            }
        } finally {
            handler.removeCallbacks(poll);
            handler.postDelayed(poll, POLL_MS);
        }
    }

    private void schedulePoll() { handler.removeCallbacks(poll); handler.post(poll); }
    @Override public void onInputDeviceAdded(int id) { schedulePoll(); }
    @Override public void onInputDeviceRemoved(int id) { schedulePoll(); }
    @Override public void onInputDeviceChanged(int id) { schedulePoll(); }

    /** The same Binder ABI validated by the device-only presence probe. */
    private static final class InputAccess {
        private final Object service;
        private final Method ids;
        private final Method device;
        private final Method enable;
        private final Method disable;
        private final Method tabletMode;
        InputAccess() throws Exception {
            IBinder binder = (IBinder) Class.forName("android.os.ServiceManager")
                    .getMethod("getService", String.class).invoke(null, "input");
            if (binder == null) throw new IllegalStateException("Input service unavailable");
            Class<?> api = Class.forName("android.hardware.input.IInputManager");
            service = Class.forName("android.hardware.input.IInputManager$Stub")
                    .getMethod("asInterface", IBinder.class).invoke(null, binder);
            ids = api.getMethod("getInputDeviceIds");
            device = api.getMethod("getInputDevice", int.class);
            enable = api.getMethod("enableInputDevice", int.class);
            disable = api.getMethod("disableInputDevice", int.class);
            tabletMode = api.getMethod("isInTabletMode");
        }
        int[] ids() throws Exception { return (int[]) ids.invoke(service); }
        InputDevice device(int id) throws Exception { return (InputDevice) device.invoke(service, id); }
        void enable(int id) throws Exception { enable.invoke(service, id); }
        void disable(int id) throws Exception { disable.invoke(service, id); }
        int tabletMode() throws Exception { return (Integer) tabletMode.invoke(service); }
    }
}
