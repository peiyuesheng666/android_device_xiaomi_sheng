// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.keyboard;

import android.content.Context;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.PowerManager;
import android.util.Log;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Restores the original version discovery and MiDev challenge/token handshake. */
final class KeyboardController implements KeyboardHal.Listener {
    private final Handler worker;
    private final Handler authWorker;
    private final KeyboardHal hal;
    private final MiDevAuthClient auth;
    private final PowerManager power;
    private final KeyboardFeatureCommands features;
    private volatile int generation;
    private volatile boolean active;
    private volatile Pending pending;
    private boolean attached;
    private boolean running;
    private boolean verified;
    private int attempts;
    private long nextAttempt;
    private int keyboardType = -1;
    private boolean awake;
    private boolean needsWake = true;
    private boolean featuresDirty = true;
    private boolean touchpadEnabled;
    private final KeyboardBacklight backlight = new KeyboardBacklight();
    private final KeyboardAutomaticBacklight automaticBacklight;
    private String lastBacklightGate;
    private final KeyboardBacklightWake backlightWake = new KeyboardBacklightWake();
    private final KeyboardStartupWake startupWake = new KeyboardStartupWake();
    private boolean lightUsable;

    KeyboardController(Context context) {
        HandlerThread thread = new HandlerThread("sheng-keyboard-link"); thread.start();
        worker = new Handler(thread.getLooper());
        automaticBacklight = new KeyboardAutomaticBacklight(context, worker);
        HandlerThread authThread = new HandlerThread("sheng-keyboard-auth"); authThread.start();
        authWorker = new Handler(authThread.getLooper());
        power = context.getSystemService(PowerManager.class);
        hal = new KeyboardHal(worker, this);
        features = new KeyboardFeatureCommands(new KeyboardFeatureCommands.Scheduler() {
            @Override public void postDelayed(Runnable task, long delay) { worker.postDelayed(task, delay); }
            @Override public void remove(Runnable task) { worker.removeCallbacks(task); }
        }, (command, enabled) -> hal.send(KeyboardProtocol.feature(command, enabled)),
                () -> active && awake && verified);
        auth = new MiDevAuthClient(context, () -> worker.post(() -> { nextAttempt = 0; attempts = 0; }));
    }

    void update(Boolean connection, boolean enableTouchpad, int brightness, int tabletMode) {
        worker.post(() -> {
            boolean usableForLight = Boolean.TRUE.equals(connection)
                    && tabletMode == 0 && power.isInteractive();
            lightUsable = usableForLight;
            if (startupWake.update(usableForLight, android.os.SystemClock.uptimeMillis())) {
                needsWake = true;
                Log.i("ShengKeyboard", "Stock bounded startup activation");
            }
            if (backlightWake.update(brightness, automaticBacklight.enabled(), usableForLight, awake)) {
                // The MCU idles independently of screen state. An explicit user
                // adjustment needs a normal activation and its real awake reply.
                // Do not set awake optimistically or wake for ambient lux changes.
                needsWake = true;
                startupWake.resumed(usableForLight, android.os.SystemClock.uptimeMillis());
            }
            if (touchpadEnabled != enableTouchpad) {
                touchpadEnabled = enableTouchpad; featuresDirty = true;
            }
            int requested = automaticBacklight.resolve(Boolean.TRUE.equals(connection)
                    && tabletMode == 0 && power.isInteractive(), brightness);
            backlight.update(connection, requested, tabletMode);
            // An unreadable state is not evidence that the keyboard was detached.
            updateOnWorker(connection == null ? attached : connection);
        });
    }
    private void updateOnWorker(boolean connected) {
        boolean usable = connected && power.isInteractive();
        if (attached != connected || active != usable) {
            attached = connected; active = usable;
            cancel(); attempts = 0; nextAttempt = 0;
            needsWake = true; awake = false;
            if (!connected) { verified = false; keyboardType = -1; }
        }
        if (!usable) return;
        if (verified) {
            if (!wakeIfNeeded()) return;
            applyFeatures();
            return;
        }
        long now = android.os.SystemClock.uptimeMillis();
        if (running || now < nextAttempt) return;
        if (attempts >= 5) { attempts = 0; nextAttempt = now + 30000; return; }
        // Dependency failures remain pending; they must never be recorded as success.
        nextAttempt = now + 5000;
        if (!hal.connect()) {
            if (++attempts == 1) Log.w("ShengKeyboard", "Original keyboard HAL unavailable");
            return;
        }
        // Initial activation; subsequent startup refreshes are bounded to 120s.
        if (!wakeIfNeeded()) return;
        auth.bind();
        if (!auth.available()) return;
        running = true;
        final int epoch = generation;
        ++attempts;
        authWorker.post(() -> authenticate(epoch));
    }

    void firmwareReloaded() {
        worker.post(() -> {
            onTransportLost();
            Log.i("ShengKeyboard", "MCU firmware reloaded; original authentication required again");
        });
    }

    private void cancel() {
        ++generation;
        Pending request = pending;
        if (request != null) request.done.countDown();
        pending = null;
        features.clear(); featuresDirty = true; backlight.invalidate();
        // The single auth worker serializes in-flight Binder calls across reconnects.
        // A stale result cannot change the new attachment's state.
    }

    @Override public void onTransportLost() {
        cancel(); verified = false; attempts = 0; nextAttempt = 0; needsWake = true; awake = false;
    }

    @Override public void onReply(byte[] reply) {
        int command = reply[4] & 0xff;
        boolean fromKeyboard = (reply[2] & 0xff) == KeyboardProtocol.KEYBOARD;
        if (fromKeyboard && reply[1] == 0x30 && command == KeyboardProtocol.VERSION) {
            int nextType = KeyboardProtocol.keyboardType(reply);
            if (nextType != keyboardType) backlight.invalidate();
            keyboardType = nextType;
            featuresDirty = true;
        }
        if (fromKeyboard && reply[1] == 0x31 && reply[5] == 1) {
            int value = reply[6] & 0xff;
            if (command == KeyboardProtocol.TOUCHPAD) features.acknowledge(command, value);
            if ((command == KeyboardProtocol.SLEEP || command == KeyboardProtocol.POWER)
                    && (value == 0 || value == 1)) {
                boolean nowAwake = value == 1;
                if (awake != nowAwake) {
                    // A real MCU sleep-status wake starts a fresh bounded window.
                    // POWER acknowledgements from our 12s refresh must never renew it.
                    if (nowAwake && command == KeyboardProtocol.SLEEP) {
                        startupWake.resumed(lightUsable, android.os.SystemClock.uptimeMillis());
                        Log.i("ShengKeyboard", "MCU input wake: restart bounded light window");
                    }
                    awake = nowAwake;
                    features.clear();
                    featuresDirty = true;
                    backlight.invalidate();
                }
            }
        }
        Pending request = pending;
        if (request != null && request.epoch == generation
                && (reply[1] & 0xff) == request.protocol
                && (reply[2] & 0xff) == request.source
                && (reply[4] & 0xff) == request.command) {
            request.reply = reply;
            request.done.countDown();
        }
        if ((reply[2] & 0xff) == KeyboardProtocol.KEYBOARD
                && (reply[4] & 0xff) == KeyboardProtocol.REQUEST && reply[5] == 1) {
            int reason = reply[6] & 0xff;
            if (reason == 100) {
                cancel(); verified = false; attempts = 0; nextAttempt = 0;
                Log.i("ShengKeyboard", "Keyboard requested original authentication");
            } else if ((reason == 0 || reason == 1) && active) {
                // Discovery is a normal response to MCU initialization, never a reset.
                hal.send(KeyboardProtocol.version(KeyboardProtocol.KEYBOARD));
            }
        }
        applyFeatures();
    }

    private void applyFeatures() {
        String gate = "active=" + active + " awake=" + awake + " verified=" + verified
                + " type=" + keyboardType + " capable=" + KeyboardProtocol.hasBacklight(keyboardType);
        if (!gate.equals(lastBacklightGate)) {
            lastBacklightGate = gate;
            Log.i("ShengKeyboard", "Backlight gate " + gate);
        }
        if (!active || !awake || !verified) return;
        if (KeyboardProtocol.hasTouchpad(keyboardType) && featuresDirty
                && features.send(KeyboardProtocol.TOUCHPAD, touchpadEnabled)) {
            featuresDirty = false;
        }
        backlight.apply(KeyboardProtocol.hasBacklight(keyboardType),
                value -> {
                    boolean submitted = hal.send(KeyboardProtocol.backlight(value));
                    if (submitted) automaticBacklight.submitted(value);
                    Log.i("ShengKeyboard", "Backlight percent=" + value + " submitted=" + submitted);
                    return submitted;
                });
    }

    private boolean wakeIfNeeded() {
        if (!needsWake) return true;
        if (!hal.connect() || !hal.send(KeyboardProtocol.feature(KeyboardProtocol.POWER, true))) return false;
        needsWake = false;
        return true;
    }

    private boolean current(int epoch) { return active && epoch == generation; }
    private byte[] request(int epoch, byte[] packet) throws Exception {
        if (!current(epoch)) return null;
        Pending waiting = new Pending(epoch, packet[5] & 0xff, packet[7] & 0xff, packet[8] & 0xff);
        pending = waiting;
        try {
            if (!hal.send(packet) || !waiting.done.await(1000, TimeUnit.MILLISECONDS) || !current(epoch)) return null;
            return waiting.reply;
        } finally { if (pending == waiting) pending = null; }
    }

    private void authenticate(int epoch) {
        String outcome = "incomplete";
        String stage = "mcu-version";
        boolean success = false;
        try {
            byte[] version = request(epoch, KeyboardProtocol.version(KeyboardProtocol.MCU));
            if (version == null || version.length < 23) throw new Exception("MCU version unavailable");
            String mcu = new String(version, 7, 16, StandardCharsets.US_ASCII).replace("\0", "").trim();
            if (mcu.isEmpty()) throw new Exception("MCU version empty");
            stage = "keyboard-version";
            byte[] keyboard = request(epoch, KeyboardProtocol.version(KeyboardProtocol.KEYBOARD));
            if (keyboard == null) throw new Exception("Keyboard version unavailable");
            stage = "identity";
            byte[] hello = request(epoch, KeyboardProtocol.authStart());
            if (hello == null || hello.length < 33 || hello[5] != 26) throw new Exception("Identity reply unavailable");
            byte[] uid = Arrays.copyOfRange(hello, 8, 24);
            stage = "key-selection";
            byte[] selected = auth.choose(uid, Arrays.copyOfRange(hello, 24, 28), Arrays.copyOfRange(hello, 28, 32));
            if (!current(epoch)) return;
            if (selected == null || selected.length != 4) throw new Exception("Original key selection failed");
            stage = "challenge-generation";
            byte[] challenge = auth.challenge();
            if (challenge == null || challenge.length != 16) throw new Exception("Original challenge unavailable");
            stage = "keyboard-token";
            byte[] answer = request(epoch, KeyboardProtocol.challenge(selected, challenge));
            boolean oldMcu = mcu.startsWith("XM2022");
            int length = oldMcu ? 16 : 32;
            if (answer == null || (answer[5] & 0xff) != length || answer.length < length + 7)
                throw new Exception("Authentication reply incomplete");
            stage = "token-verification";
            int verdict = auth.verify(uid, selected, challenge, Arrays.copyOfRange(answer, 6, 22));
            if (!current(epoch)) return;
            if (verdict != 1 && verdict != 2) throw new Exception("Original token verification failed");
            if (!oldMcu) {
                stage = "mutual-token";
                byte[] token = auth.token(uid, selected, Arrays.copyOfRange(answer, 22, 38));
                if (token == null || token.length != 16 || !current(epoch) || !hal.send(KeyboardProtocol.token(token)))
                    throw new Exception("Mutual authentication incomplete");
                Arrays.fill(token, (byte) 0);
            }
            Arrays.fill(uid, (byte) 0); Arrays.fill(challenge, (byte) 0); Arrays.fill(selected, (byte) 0);
            outcome = verdict == 1 ? "verified with original online key" : "verified with original offline key";
            success = true;
        } catch (Exception | LinkageError error) {
            // Do not expose OEM exception payloads, device IDs, keys or tokens.
            outcome = "incomplete at " + stage + " (" + error.getClass().getSimpleName() + ")";
        } finally {
            final boolean accepted = success;
            final String status = outcome;
            worker.post(() -> {
                running = false;
                if (epoch != generation) return;
                verified = accepted;
                if (accepted) { featuresDirty = true; applyFeatures(); }
                nextAttempt = android.os.SystemClock.uptimeMillis() + 5000;
                Log.i("ShengKeyboard", "Original authentication " + status);
            });
        }
    }

    private static final class Pending {
        final int epoch, protocol, source, command;
        final CountDownLatch done = new CountDownLatch(1);
        volatile byte[] reply;
        Pending(int epoch, int protocol, int source, int command) {
            this.epoch = epoch; this.protocol = protocol; this.source = source; this.command = command;
        }
    }
}
