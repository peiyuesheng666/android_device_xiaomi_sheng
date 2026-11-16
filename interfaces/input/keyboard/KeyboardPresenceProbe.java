// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.keyboard;

import android.net.LocalServerSocket;
import android.os.IBinder;
import android.os.SystemClock;
import android.view.InputDevice;

import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Temporary presence test. Restores every device it disables before normal exit. */
public final class KeyboardPresenceProbe {
    private static final String STATUS = "/sys/class/nanodev/nanodev0/_version176x";
    private static final Pattern KEY = Pattern.compile("(?<![A-Za-z0-9_])Connected\\s*=");
    private static final Pattern VALUE = Pattern.compile("\\s*\\[\\s*([01])\\s*\\]");

    private final Object input;
    private final Method ids;
    private final Method device;
    private final Method enable;
    private final Method disable;
    private final Method tabletMode;
    private final Set<Integer> disabledHere = new HashSet<>();

    private KeyboardPresenceProbe() throws Exception {
        Class<?> services = Class.forName("android.os.ServiceManager");
        IBinder binder = (IBinder) services.getMethod("getService", String.class)
                .invoke(null, "input");
        if (binder == null) throw new IllegalStateException("Input service unavailable");
        Class<?> stub = Class.forName("android.hardware.input.IInputManager$Stub");
        Class<?> api = Class.forName("android.hardware.input.IInputManager");
        input = stub.getMethod("asInterface", IBinder.class).invoke(null, binder);
        ids = api.getMethod("getInputDeviceIds");
        device = api.getMethod("getInputDevice", int.class);
        enable = api.getMethod("enableInputDevice", int.class);
        disable = api.getMethod("disableInputDevice", int.class);
        tabletMode = api.getMethod("isInTabletMode");
    }

    static Boolean connected(String text) {
        Matcher key = KEY.matcher(text);
        if (!key.find()) return null;
        Matcher value = VALUE.matcher(text.substring(key.end()));
        if (!value.lookingAt() || key.find()) return null;
        return "1".equals(value.group(1));
    }

    private static Boolean readConnected() throws Exception {
        return connected(new String(Files.readAllBytes(Paths.get(STATUS)), StandardCharsets.UTF_8));
    }

    private static boolean pogo(InputDevice d) {
        if (d == null || d.getVendorId() != 0x15d9) return false;
        switch (d.getProductId()) {
            case 0x00a1: return "Xiaomi Touch".equals(d.getName());
            case 0x00a2: return "Xiaomi Mouse".equals(d.getName());
            case 0x00a3: return "Xiaomi Keyboard".equals(d.getName());
            case 0x00a4: return "Xiaomi Consumer".equals(d.getName());
            default: return false;
        }
    }

    private void snapshot(Boolean state) throws Exception {
        System.out.println("Connected=" + state + " tabletMode=" + tabletMode.invoke(input));
        for (int id : (int[]) ids.invoke(input)) {
            InputDevice d = (InputDevice) device.invoke(input, id);
            if (pogo(d)) System.out.println("id=" + id + " name=" + d.getName()
                    + " keyboardType=" + d.getKeyboardType()
                    + " enabled=" + d.isEnabled());
        }
    }

    private void reconcile(boolean state) throws Exception {
        if (state) {
            restore();
            return;
        }
        for (int id : (int[]) ids.invoke(input)) {
            InputDevice d = (InputDevice) device.invoke(input, id);
            if (pogo(d) && d.isEnabled()) {
                // Record before the RPC, so uncertain completion is also restored.
                disabledHere.add(id);
                disable.invoke(input, id);
                System.out.println("Disconnected pogo input disabled: " + id);
            }
        }
    }

    private void restore() throws Exception {
        for (int id : new HashSet<>(disabledHere)) {
            InputDevice d = (InputDevice) device.invoke(input, id);
            if (pogo(d)) enable.invoke(input, id);
            disabledHere.remove(id);
            System.out.println("Probe-owned input restored: " + id);
        }
    }

    private void watch(long durationMs) throws Exception {
        Boolean applied = null;
        Boolean pending = null;
        long since = 0;
        long end = SystemClock.elapsedRealtime() + durationMs;
        try {
            while (SystemClock.elapsedRealtime() < end) {
                Boolean state = readConnected();
                long now = SystemClock.elapsedRealtime();
                if (state == null) throw new IllegalStateException("Ambiguous connection state");
                int fold = (Integer) tabletMode.invoke(input);
                if (fold != 0 && fold != 1) throw new IllegalStateException("Unknown fold state");
                boolean usable = state && fold == 0;
                if (!Boolean.valueOf(usable).equals(pending)) { pending = usable; since = now; }
                if (fold == 1 || now - since >= 1000) {
                    reconcile(usable);
                    if (!Boolean.valueOf(usable).equals(applied)) { applied = usable; snapshot(state); }
                }
                Thread.sleep(250);
            }
        } finally {
            restore();
        }
    }

    public static void main(String[] args) throws Exception {
        KeyboardPresenceProbe probe = new KeyboardPresenceProbe();
        if (args.length == 0 || (args.length == 1 && "--probe".equals(args[0]))) {
            probe.snapshot(readConnected());
            return;
        }
        if (args.length != 2 || !"--watch".equals(args[0])) {
            throw new IllegalArgumentException("Use --probe or --watch <seconds>");
        }
        int seconds = Integer.parseInt(args[1]);
        if (seconds < 1 || seconds > 300) throw new IllegalArgumentException("Lifetime 1..300s");
        try (LocalServerSocket owner = new LocalServerSocket("sheng-keyboard-presence-probe")) {
            probe.snapshot(readConnected());
            probe.watch(seconds * 1000L);
        }
    }
}
