// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

import android.bluetooth.*;
import android.app.ActivityManager;
import android.content.Context;
import android.hardware.display.DisplayManager;
import android.os.Binder;
import android.os.Handler;
import android.os.SystemClock;
import android.util.Log;
import android.view.Display;
import vendor.lineage.sheng.stylus.IPenController;
import java.util.ArrayDeque;
import java.util.UUID;
import java.util.function.Consumer;
import org.lineageos.sheng.pen.controls.PenControlsSettings;

/** All callbacks and hardware operations run on the application's single actor. */
final class PenGattSession extends BluetoothGattCallback {
    private static UUID sig(String id) {
        return UUID.fromString("0000" + id + "-0000-1000-8000-00805f9b34fb");
    }
    private static final UUID SERVICE = UUID.fromString("0000fe10-aa6c-462a-964a-7f2ed5b3e512");
    private static final UUID COMMAND = UUID.fromString("0000fe11-aa6c-462a-964a-7f2ed5b3e512");
    private static final UUID REPLY = UUID.fromString("0000fe12-aa6c-462a-964a-7f2ed5b3e512");
    private static final UUID CCCD = sig("2902"), PNP = sig("2a50");
    private final Context context;
    private final Handler actor;
    private final BluetoothDevice device;
    private final BluetoothAdapter adapter;
    private final IPenController controller;
    private final PenInputLease inputs;
    private final DisplayManager displays;
    private final DisplayRateLease rate;
    private final Binder owner = new Binder();
    private final Runnable finished;
    private final PenShortcutController buttons;
    private final ArrayDeque<BluetoothGattDescriptor> references = new ArrayDeque<>();
    private final ArrayDeque<Integer> frequencies = new ArrayDeque<>();
    private final ArrayDeque<FeatureRequest> features = new ArrayDeque<>();
    private BluetoothGatt client;
    private BluetoothGattCharacteristic command, reply, pressure, buttonReport;
    private PenPanelObserver panel;
    private PenModel model;
    private int product, firstId, secondId, query, currentDock = -1, notifiedDock = -1;
    private int active = -1, expectedOpcode, expectedLength;
    private byte[] localAddress, response;
    private boolean closed, owned, awake, rateHeld, initialized, ready, resuming, pausing, needsResume;
    private boolean writeDone;
    private boolean buttonSubscribed, ambiguousButtons, featurePending;
    private int attemptedSensitivity = -1, attemptedVibration = -1;
    private boolean controlPending;
    private boolean screenOnSubmitted, restoreScreenOn, screenStatusOnly, nativeReadyAfterWake;
    private int screenStatusRequested;
    private final PenWakeGate wakeGate = new PenWakeGate();
    private String pendingKind;
    private Object pendingObject;
    private Consumer<byte[]> completion;
    private Runnable deferred;
    private final Runnable timeout = this::operationTimeout;
    private final Runnable connectionTimeout = () -> close("GATT connection timeout");

    PenGattSession(Context context, Handler actor, BluetoothDevice device, BluetoothAdapter adapter,
            IPenController controller, PenInputLease inputs, DisplayManager displays, Runnable finished) {
        this.context = context; this.actor = actor; this.device = device; this.adapter = adapter;
        this.controller = controller; this.inputs = inputs; this.displays = displays;
        this.finished = finished; rate = new DisplayRateLease(context);
        buttons = new PenShortcutController(context, actor, this::requestHaptic);
    }
    String address() { return device.getAddress(); }
    void start() {
        try {
            String address = adapter.getAddress();
            if (!BluetoothAdapter.checkBluetoothAddress(address) || "02:00:00:00:00:00".equals(address)
                    || "00:00:00:00:00:00".equals(address)) throw new IllegalStateException("Local address unavailable");
            localAddress = new byte[6];
            String[] pieces = address.split(":");
            for (int i = 0; i < 6; i++) localAddress[i] = (byte) Integer.parseInt(pieces[i], 16);
            holdDisplay();
            client = device.connectGatt(context, false, this, BluetoothDevice.TRANSPORT_LE);
            if (client == null) { close("GATT connection rejected"); return; }
            actor.postDelayed(connectionTimeout, 45000);
        } catch (Exception error) { fail("start", error); }
    }

    private void holdDisplay() throws Exception {
        if (!rateHeld) { rate.acquire(120); rateHeld = true; }
    }
    private void releaseDisplay() {
        try { rate.close(); rateHeld = false; }
        catch (Exception error) {
            Log.w(ShengStylusApplication.TAG, "Display vote removal deferred", error);
            // Keep the token reachable until the release succeeds. Process
            // death independently removes this DisplayManager request.
            actor.postDelayed(() -> { if (closed || !awake || (initialized && currentDock == 0)) releaseDisplay(); }, 1000);
        }
    }
    private boolean displayEligible() {
        Display display = displays.getDisplay(Display.DEFAULT_DISPLAY);
        return rateHeld && display != null
                && display.getState() == Display.STATE_ON
                && display.getMode().getRefreshRate() >= 59.9f
                && display.getMode().getRefreshRate() <= 120.1f;
    }
    private boolean canWrite() {
        return wakeGate.ready(awake, currentDock >= 0 && displayEligible(), SystemClock.uptimeMillis());
    }

    void observe(boolean on, int dock) {
        if (closed) return;
        boolean wentOff = awake && !on;
        awake = on; currentDock = dock;
        // A docked pen must still observe screen On/Off. Releasing its 120 Hz
        // cap does not turn the screen off or restart the panel's wake interval.
        wakeGate.observe(on, SystemClock.uptimeMillis());
        buttons.setAvailable(on && ready && dock == 1 && buttonSubscribed);
        if (!on || dock != 1) {
            features.clear(); attemptedSensitivity = -1; attemptedVibration = -1;
        }
        if (!on) {
            if (wentOff || ready) { ready = false; needsResume = initialized; }
            if (wentOff) nativeReadyAfterWake = false;
            releaseDisplay();
            maybeSendScreenOff();
            return;
        }
        if (dock < 0) { close("Dock state unavailable while On"); return; }
        try {
            if (owned && controller.getForwardedCount(owner) < 0) { close("native lease lost"); return; }
            // Java-side waiting does not suspend the native worker. Release
            // ownership before removing our vote or leaving an active native
            // controller at an unsupported actual rate, including setup before
            // the pressure subscription ACK marks the Java session ready.
            if (owned && nativeReadyAfterWake && !displayEligible()) {
                close("Active pen display constraints lost"); return;
            }
            if (owned && !inputs.guard(model, product, address())) return;
            if (!initialized || dock == 1 || notifiedDock != dock || deferred != null
                    || pendingKind != null || pausing || restoreScreenOn) holdDisplay();
            if (!canWrite()) return;
            // Screen status is a GATT-only transaction. Restore it before
            // resuming any continuation interrupted by Off, including setup
            // that has not reached initialized yet.
            if (restoreScreenOn) {
                if (pendingKind == null) sendScreenStatus(true);
                return;
            }
            if (deferred != null) {
                Runnable action = deferred; deferred = null; action.run(); return;
            }
            if (pendingKind != null || controlPending || resuming || pausing) return;
            if (initialized && dock == 0) {
                if (ready || notifiedDock != 0) pauseDocked();
                else releaseDisplay();
            } else if (initialized && (!ready || needsResume || notifiedDock != 1)) resume();
            else drain();
        } catch (Exception error) { fail("observe", error); }
    }

    void close(String reason) {
        if (closed) return;
        closed = true; deferred = null;
        buttons.close(); features.clear();
        actor.removeCallbacks(timeout); actor.removeCallbacks(connectionTimeout);
        // Bluetooth/service teardown can throw before its own bookkeeping
        // finishes. Attempt each resource independently so a failed disconnect
        // cannot strand the native owner, disabled input or application session.
        if (panel != null) {
            try { panel.close(); }
            catch (RuntimeException error) { Log.w(ShengStylusApplication.TAG, "Panel observer close failed", error); }
        }
        if (client != null) {
            try { client.disconnect(); }
            catch (RuntimeException error) { Log.w(ShengStylusApplication.TAG, "GATT disconnect failed", error); }
            try { client.close(); }
            catch (RuntimeException error) { Log.w(ShengStylusApplication.TAG, "GATT close failed", error); }
        }
        if (owned) {
            try { Log.i(ShengStylusApplication.TAG, "Owned release=" + controller.release(owner)); }
            catch (Exception error) { Log.w(ShengStylusApplication.TAG, "Native release deferred/dead", error); }
            owned = false;
        }
        try { inputs.restore(); }
        catch (Exception error) { Log.e(ShengStylusApplication.TAG, "Input journal retained", error); }
        releaseDisplay();
        Log.i(ShengStylusApplication.TAG, "Session closed: " + reason);
        finished.run();
    }
    private void fail(String stage, Exception error) {
        Log.e(ShengStylusApplication.TAG, stage + " failed", error); close(stage + " failure");
    }

    private void later(Runnable action) {
        if (closed) return;
        if (!canWrite() || restoreScreenOn) { deferred = action; return; }
        try { action.run(); } catch (RuntimeException error) { fail("actor continuation", error); }
    }
    private void begin(String kind, Object object, Consumer<byte[]> next) {
        if (pendingKind != null) throw new IllegalStateException("Overlapping GATT operation");
        pendingKind = kind; pendingObject = object; completion = next;
        actor.postDelayed(timeout, 15000);
    }
    private void done(byte[] value) {
        actor.removeCallbacks(timeout);
        featurePending = false;
        Consumer<byte[]> next = completion;
        completion = null; pendingKind = null; pendingObject = null;
        byte[] copy = value == null ? new byte[0] : value.clone();
        if (screenStatusOnly) {
            screenStatusOnly = false;
            if (screenStatusRequested == 1) restoreScreenOn = false;
            // Preserve the ordinary deferred continuation. A status ACK must
            // neither replace it nor run driver operations during Off.
            if (!awake) maybeSendScreenOff();
            else observe(awake, currentDock);
            return;
        }
        later(() -> { next.accept(copy); drain(); });
        maybeSendScreenOff();
    }
    private boolean matching(BluetoothGatt g, String kind, Object object) {
        return !closed && g == client && kind.equals(pendingKind) && object == pendingObject;
    }
    private void read(BluetoothGattCharacteristic characteristic, Consumer<byte[]> next) {
        if (characteristic == null) { close("Required characteristic unavailable"); return; }
        begin("read", characteristic, next);
        if (!client.readCharacteristic(characteristic)) close("Characteristic read rejected");
    }
    private void subscribe(BluetoothGattCharacteristic characteristic, Runnable next) {
        BluetoothGattDescriptor cccd = characteristic == null ? null : characteristic.getDescriptor(CCCD);
        if (cccd == null || (characteristic.getProperties() & BluetoothGattCharacteristic.PROPERTY_NOTIFY) == 0
                || !client.setCharacteristicNotification(characteristic, true)) {
            close("Notification endpoint unavailable"); return;
        }
        begin("descriptor-write", cccd, ignored -> next.run());
        if (client.writeDescriptor(cccd, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)
                != BluetoothStatusCodes.SUCCESS) close("Notification write submission rejected");
        // HidHost shares the physical CCCD. Never write an invented previous
        // value or disable it on logical GATT client cleanup.
    }
    private void exchange(byte[] bytes, int length, Consumer<byte[]> next) {
        begin("command", command, next);
        if (model == PenModel.PRO && bytes.length == 3 && bytes[0] == 0x61)
            screenOnSubmitted = bytes[2] == 1;
        expectedOpcode = bytes[0] & 255; expectedLength = length;
        writeDone = false; response = null;
        int type = (command.getProperties() & BluetoothGattCharacteristic.PROPERTY_WRITE) != 0
                ? BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT : BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE;
        if (client.writeCharacteristic(command, bytes, type) != BluetoothStatusCodes.SUCCESS) {
            if (featurePending) done(null);
            else close("MIPP write submission rejected");
        }
    }
    private void commandDone() {
        if (writeDone && response != null) { byte[] value = response; response = null; done(value); }
    }

    private void operationTimeout() {
        // A missing accessory ACK after a completed ATT write need not tear
        // down pressure. An ATT operation with no completion remains fatal.
        if (featurePending && writeDone) {
            Log.w("ShengPenButtons", "Accessory command reply timed out"); done(null);
        } else close("GATT operation timeout");
    }

    private void maybeSendScreenOff() {
        if (!closed && !awake && model == PenModel.PRO && client != null
                && screenOnSubmitted && pendingKind == null) sendScreenStatus(false);
    }
    private void sendScreenStatus(boolean on) {
        try {
            screenStatusOnly = true; screenStatusRequested = on ? 1 : 0;
            if (!on) restoreScreenOn = true;
            exchange(MippProfile.proScreenState(model, on), 0, ignored -> {});
        } catch (RuntimeException error) { fail("screen status", error); }
    }

    @Override public void onConnectionStateChange(BluetoothGatt g, int status, int state) {
        actor.post(() -> {
            if (closed || g != client) return;
            if (status != 0 || state != BluetoothProfile.STATE_CONNECTED) { close("GATT disconnected/status=" + status); return; }
            actor.removeCallbacks(connectionTimeout);
            begin("discovery", g, ignored -> identify());
            if (!g.discoverServices()) close("Service discovery rejected");
        });
    }
    @Override public void onServicesDiscovered(BluetoothGatt g, int status) {
        actor.post(() -> {
            if (!matching(g, "discovery", g)) return;
            if (status != 0) { close("Service discovery status=" + status); return; }
            BluetoothGattService mipp = g.getService(SERVICE);
            command = mipp == null ? null : mipp.getCharacteristic(COMMAND);
            reply = mipp == null ? null : mipp.getCharacteristic(REPLY);
            if (command == null || reply == null) { close("MIPP endpoints missing"); return; }
            done(null);
        });
    }
    private void identify() {
        BluetoothGattService information = client.getService(sig("180a"));
        read(information == null ? null : information.getCharacteristic(PNP), value -> {
            model = PenModel.fromPnp(value);
            if (model == null) { close("Unsupported PnP identity"); return; }
            product = (value[3] & 255) | ((value[4] & 255) << 8);
            Log.i("ShengPenButtons", "PnP product=0x" + Integer.toHexString(product) + " model=" + model);
            String expected = model == PenModel.PRO ? "Xiaomi Focus Pen Pro" : "Xiaomi Focus Pen";
            if (!expected.equals(device.getName())) { close("Name/PnP mismatch"); return; }
            subscribe(reply, () -> {
                begin("mtu", client, ignored -> query());
                if (!client.requestMtu(512)) close("MTU request rejected");
            });
        });
    }
    @Override public void onMtuChanged(BluetoothGatt g, int mtu, int status) {
        actor.post(() -> {
            if (!matching(g, "mtu", g)) return;
            if (status != 0 || mtu < 35) { close("MIPP MTU unavailable"); return; }
            done(null);
        });
    }
    @Override public void onCharacteristicRead(BluetoothGatt g, BluetoothGattCharacteristic c, byte[] value, int status) {
        final byte[] copy = value == null ? null : value.clone();
        actor.post(() -> {
            if (!matching(g, "read", c)) return;
            if (status != 0) { close("Characteristic read status=" + status); return; }
            done(copy);
        });
    }
    @Override public void onDescriptorWrite(BluetoothGatt g, BluetoothGattDescriptor d, int status) {
        actor.post(() -> {
            if (matching(g, "button-subscribe", d)) {
                buttonSubscribed = status == 0;
                Log.i("ShengPenButtons", "Keyboard report subscription status=" + status);
                done(null); return;
            }
            if (!matching(g, "descriptor-write", d)) return;
            if (status != 0) { close("Notification subscription status=" + status); return; }
            done(null);
        });
    }
    @Override public void onDescriptorRead(BluetoothGatt g, BluetoothGattDescriptor d, int status, byte[] value) {
        final byte[] copy = value == null ? null : value.clone();
        actor.post(() -> {
            if (!matching(g, "descriptor-read", d)) return;
            if (status != 0) { close("Report reference status=" + status); return; }
            done(copy);
        });
    }
    @Override public void onCharacteristicWrite(BluetoothGatt g, BluetoothGattCharacteristic c, int status) {
        actor.post(() -> {
            if (!matching(g, "command", c)) return;
            if (status != 0) {
                if (featurePending) done(null);
                else close("MIPP write status=" + status);
                return;
            }
            writeDone = true; commandDone();
        });
    }
    @Override public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c, byte[] value) {
        final byte[] copy = value == null ? new byte[0] : value.clone();
        actor.post(() -> {
            if (closed || g != client) return;
            if (c == buttonReport && buttonSubscribed) {
                boolean usable = model == PenModel.PRO && initialized && ready && awake && currentDock == 1;
                Log.d("ShengPenButtons", "HID report2=" + java.util.Arrays.toString(copy) + " usable=" + usable);
                buttons.setAvailable(usable);
                if (usable) buttons.report(copy);
                return;
            }
            if (c != reply) return;
            // GATT pressure is never submitted to the server. It forwards only
            // the matching, descriptor-verified, physical hidraw input.
            if (model == PenModel.PRO && copy.length == 3 && (copy[0] & 255) == 0x53
                    && copy[1] == 1 && (copy[2] == 0 || copy[2] == 1)) {
                active = copy[2]; drain(); return;
            }
            if (!"command".equals(pendingKind) || copy.length < 2
                    || (copy[0] & 255) != (expectedOpcode | 128)) return;
            if (copy.length != expectedLength + 2 || (copy[1] & 255) != expectedLength) {
                if (featurePending) { response = new byte[0]; commandDone(); return; }
                close("Malformed MIPP reply"); return;
            }
            if (model == PenModel.PRO && expectedOpcode == 0x52) {
                if (copy[2] != 0 && copy[2] != 1) { close("Invalid Pro active state"); return; }
                // Both the query reply and unsolicited state use this ordered
                // mailbox. The write ACK may arrive after either of them.
                active = copy[2];
            }
            response = copy; commandDone();
        });
    }

    private void query() {
        exchange(new byte[] {(byte) query, 0}, new int[] {1, 2, 2, 3}[query], value -> {
            if (++query < 4) query(); else acquire(0);
        });
    }
    private void queryActiveState(Runnable next) {
        exchange(new byte[] {0x52, 0}, 1, value -> {
            // The query supersedes earlier notifications. A notification that
            // followed its reply supersedes the query, even before the write
            // ACK or a deferred wake continuation completes.
            int state = active >= 0 ? active : value[2] & 255;
            active = -1;
            mode(29, state, next);
        });
    }
    private void acquire(int attempt) {
        controlPending = true;
        later(() -> {
            try {
                int result = controller.acquire(owner, product, address());
                if (result == IPenController.APPLIED) {
                    owned = true; controlPending = false;
                    panel = new PenPanelObserver(actor, this::frequencyRequest); panel.start();
                    guard(0);
                } else if ((result == IPenController.DEFERRED || result == IPenController.INVALID
                        || result == IPenController.BUSY) && attempt < 20) {
                    actor.postDelayed(() -> { if (!closed) acquire(attempt + 1); }, 500);
                } else close("Native acquire result=" + result);
            } catch (Exception error) { fail("acquire", error); }
        });
    }
    private void guard(int attempt) {
        // A delayed InputManager reconfiguration can finish after Off. Route
        // the retry through the same awake/display gate as every continuation.
        later(() -> {
          try {
            if (!inputs.guard(model, product, address())) {
                if (attempt >= 10) { close("Pro input guard unavailable"); return; }
                actor.postDelayed(() -> guard(attempt + 1), 500); return;
            }
            if (model == PenModel.PRO) queryActiveState(() -> assign(false));
            else assign(false);
          } catch (Exception error) { fail("input guard", error); }
        });
    }
    private void mode(int mode, int value, Runnable next) {
        if (controlPending) { close("Overlapping controller operation"); return; }
        controlPending = true;
        mode(mode, value, next, 0);
    }
    private void mode(int mode, int value, Runnable next, int attempt) {
        later(() -> {
            try {
                int result = controller.setMode(owner, mode, value);
                if (result == IPenController.APPLIED) {
                    if (mode == 37) nativeReadyAfterWake = value == 1;
                    controlPending = false; next.run();
                }
                else if (result == IPenController.DEFERRED && attempt < 10)
                    actor.postDelayed(() -> { if (!closed) mode(mode, value, next, attempt + 1); }, 500);
                else close("Controller mode=" + mode + " result=" + result);
            } catch (Exception error) { fail("controller mode", error); }
        });
    }
    private void assign(boolean second) {
        exchange(new byte[] {4, 0}, 1, value -> {
            int id = value[2] & 255;
            if (second) secondId = id; else firstId = id;
            // Stock accepts the byte ABI, including 255. IDs are allocated
            // only once per logical connection, never repeatedly on wake.
            mode(22, (id << 8) | (second ? 3 : 1), () ->
                exchange(MippProfile.parameters(localAddress, id, second), 0, ignored ->
                    exchange(MippProfile.frequency(id, 0), 0, ignored2 ->
                        exchange(MippProfile.voltage(id), 0, ignored3 -> {
                            if (!second) assign(true); else finishTiming(true);
                        }))));
        });
    }
    private void finishTiming(boolean initial) {
        exchange(MippProfile.timestamp(System.currentTimeMillis() / 1000), 0, ignored -> {
            int state = currentDock;
            exchange(new byte[] {0x51, 1, (byte) state}, 0, ignored2 -> {
                notifiedDock = state;
                Runnable makeReady = () -> mode(37, 1, () ->
                    exchange(MippProfile.parameters(localAddress, secondId, false), 0, ignored3 -> {
                        if (initial && model == PenModel.PRO) pressureReferences(); else complete();
                    }));
                if (model == PenModel.PRO) exchange(MippProfile.proScreenState(model, true), 0, ignored3 -> {
                    if (initial) makeReady.run();
                    else queryActiveState(makeReady);
                });
                else makeReady.run();
            });
        });
    }
    private void pressureReferences() {
        BluetoothGattService hid = client.getService(sig("1812"));
        if (hid == null) { close("HID service missing"); return; }
        for (BluetoothGattCharacteristic c : hid.getCharacteristics()) {
            if (!c.getUuid().equals(sig("2a4d"))) continue;
            BluetoothGattDescriptor reference = c.getDescriptor(sig("2908"));
            if (reference != null) references.add(reference);
        }
        nextReference();
    }
    private void nextReference() {
        if (references.isEmpty()) {
            if (pressure == null) { close("Exact pressure input report missing"); return; }
            subscribe(pressure, this::subscribeButtons); return;
        }
        BluetoothGattDescriptor reference = references.remove();
        begin("descriptor-read", reference, value -> {
            if (value.length != 2) { close("Invalid report reference"); return; }
            if (value[0] == 5 && value[1] == 1) {
                if (pressure != null) { close("Ambiguous report 5"); return; }
                pressure = reference.getCharacteristic();
            } else if (value[0] == 2 && value[1] == 1) {
                if (buttonReport != null) ambiguousButtons = true;
                buttonReport = reference.getCharacteristic();
            }
            nextReference();
        });
        if (!client.readDescriptor(reference)) close("Report reference submission rejected");
    }
    private void subscribeButtons() {
        BluetoothGattDescriptor cccd = buttonReport == null ? null : buttonReport.getDescriptor(CCCD);
        if (ambiguousButtons || cccd == null
                || (buttonReport.getProperties() & BluetoothGattCharacteristic.PROPERTY_NOTIFY) == 0
                || !client.setCharacteristicNotification(buttonReport, true)) {
            Log.w("ShengPenButtons", "Keyboard report unavailable; writing remains available");
            complete(); return;
        }
        begin("button-subscribe", cccd, ignored -> complete());
        if (client.writeDescriptor(cccd, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)
                != BluetoothStatusCodes.SUCCESS) done(null);
    }
    private void complete() {
        initialized = true; ready = nativeReadyAfterWake; resuming = false;
        needsResume = !nativeReadyAfterWake;
        Log.i(ShengStylusApplication.TAG, "MIPP ready type=" + model.touchType
                + " ids=" + firstId + "/" + secondId + "; physical writing remains to be verified");
        observe(awake, currentDock);
    }
    private void resume() {
        resuming = true; ready = false;
        buttons.setAvailable(false);
        mode(37, 0, () -> mode(22, (firstId << 8) | 1, () ->
                mode(22, (secondId << 8) | 3, () -> finishTiming(false))));
    }
    private void pauseDocked() {
        buttons.setAvailable(false);
        pausing = true;
        mode(37, 0, () -> {
            ready = false;
            exchange(new byte[] {0x51, 1, 0}, 0, ignored -> {
                notifiedDock = 0; pausing = false; releaseDisplay();
            });
        });
    }
    private void frequencyRequest(int value) {
        if (closed || ((value >>> 16) & 255) != 0x31 || (value & 255) > 3) return;
        if (frequencies.size() >= 8) { close("Frequency request overflow"); return; }
        frequencies.add(value); drain();
    }
    private void drain() {
        if (closed || !initialized || !ready || pendingKind != null || controlPending || deferred != null
                || resuming || pausing || !canWrite()) return;
        if (active >= 0 && model == PenModel.PRO) {
            int state = active; active = -1;
            mode(29, state, this::drain); return;
        }
        if (!frequencies.isEmpty()) {
            int value = frequencies.remove();
            exchange(MippProfile.frequency((value >>> 8) & 255, value & 255), 0, ignored -> mode(22, 49, this::drain));
            return;
        }
        drainFeatures();
    }

    private static final class FeatureRequest {
        final byte[] bytes;
        final long deadline;
        FeatureRequest(byte[] bytes, long deadline) { this.bytes = bytes; this.deadline = deadline; }
    }
    private void requestHaptic(int kind) {
        if (closed || model != PenModel.PRO || !initialized || !ready || !awake || currentDock != 1
                || features.size() >= 8) return;
        int user = ActivityManager.getCurrentUser();
        if (PenControlsSettings.vibration(context, user) == 0) return;
        features.add(new FeatureRequest(PenFeatureCommands.haptic(kind,
                PenControlsSettings.sensitivity(context, user)), SystemClock.uptimeMillis() + 750));
        drain();
    }
    private void drainFeatures() {
        if (model != PenModel.PRO || !buttonSubscribed || currentDock != 1) return;
        int user = ActivityManager.getCurrentUser();
        int sensitivity = PenControlsSettings.sensitivity(context, user);
        int vibration = PenControlsSettings.vibration(context, user);
        if (features.isEmpty() && (sensitivity != attemptedSensitivity || vibration != attemptedVibration)) {
            attemptedSensitivity = sensitivity; attemptedVibration = vibration;
            for (byte[] bytes : PenFeatureCommands.configure(sensitivity, vibration))
                features.add(new FeatureRequest(bytes, 0));
        }
        while (!features.isEmpty()) {
            FeatureRequest request = features.remove();
            if (request.deadline != 0 && SystemClock.uptimeMillis() > request.deadline) continue;
            featurePending = true;
            exchange(request.bytes, PenFeatureCommands.replyLength(request.bytes), value -> {
                boolean accepted = PenFeatureCommands.accepted(request.bytes, value);
                Log.i("ShengPenButtons", "Accessory command 0x" + Integer.toHexString(request.bytes[0] & 255)
                        + (accepted ? " accepted" : " unavailable"));
                if (!accepted) features.clear();
            });
            return;
        }
    }
}
