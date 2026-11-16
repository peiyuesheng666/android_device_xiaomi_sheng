// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

import android.app.Application;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.hardware.display.DisplayManager;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.PowerManager;
import android.os.ServiceManager;
import android.os.SystemClock;
import android.os.UEventObserver;
import android.os.UserHandle;
import android.util.Log;
import android.view.Display;
import vendor.lineage.sheng.stylus.IPenController;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import org.lineageos.sheng.pen.charge.ChargeStatus;

/** Dock pairing and a single hardware/GATT actor for the connected supported pen. */
public final class ShengStylusApplication extends Application {
    static final String TAG = "ShengStylus";
    private Handler actor;
    private BluetoothAdapter bluetooth;
    private DisplayManager displays;
    private PowerManager power;
    private PenInputLease inputs;
    private PenGattSession session;
    private int failures, lastDock = -1;
    private long retryAt;
    private String retryAddress;
    private boolean lastAwake;
    private PenChargingMonitor charging;
    private String dockPeer;
    private long dockPeerSince, pairingRetryAt;
    private int pairingAttempts;
    private Intent pendingDockPairing;
    private final Runnable reconcileEvent = this::reconcile;
    private final UEventObserver dockEvents = new UEventObserver() {
        @Override public void onUEvent(UEvent event) { requestReconcile(); }
    };
    private final DisplayManager.DisplayListener displayEvents = new DisplayManager.DisplayListener() {
        @Override public void onDisplayAdded(int id) { if (id == Display.DEFAULT_DISPLAY) requestReconcile(); }
        @Override public void onDisplayRemoved(int id) { if (id == Display.DEFAULT_DISPLAY) requestReconcile(); }
        @Override public void onDisplayChanged(int id) { if (id == Display.DEFAULT_DISPLAY) requestReconcile(); }
    };

    @Override public void onCreate() {
        super.onCreate();
        HandlerThread thread = new HandlerThread("ShengStylusActor");
        thread.start(); actor = new Handler(thread.getLooper());
        displays = getSystemService(DisplayManager.class);
        power = getSystemService(PowerManager.class);
        BluetoothManager manager = getSystemService(BluetoothManager.class);
        bluetooth = manager == null ? null : manager.getAdapter();
        IntentFilter filter = new IntentFilter();
        filter.addAction(BluetoothAdapter.ACTION_STATE_CHANGED);
        filter.addAction(BluetoothDevice.ACTION_ACL_CONNECTED);
        filter.addAction(BluetoothDevice.ACTION_ACL_DISCONNECTED);
        filter.addAction(BluetoothDevice.ACTION_BOND_STATE_CHANGED);
        filter.addAction(Intent.ACTION_SCREEN_ON);
        filter.addAction(Intent.ACTION_SCREEN_OFF);
        registerReceiver(new BroadcastReceiver() {
            @Override public void onReceive(Context context, Intent intent) {
                // Polling is authoritative. A spoofed/missed broadcast cannot
                // choose a device or bypass identity, On settling, or retry caps.
                requestReconcile();
            }
        }, filter, Context.RECEIVER_NOT_EXPORTED);
        IntentFilter pairingFilter = new IntentFilter(BluetoothDevice.ACTION_PAIRING_REQUEST);
        pairingFilter.setPriority(1000);
        registerReceiver(new BroadcastReceiver() {
            @Override public void onReceive(Context context, Intent intent) {
                if (confirmDockPairing(intent)) {
                    if (isOrderedBroadcast()) abortBroadcast();
                } else {
                    showDockPairingDialog(intent);
                }
            }
        }, pairingFilter, android.Manifest.permission.BLUETOOTH_PRIVILEGED,
                actor, Context.RECEIVER_EXPORTED);
        // Events only prompt a fresh authoritative read. Their payload cannot
        // set dock state, choose a Bluetooth peer or bypass the wake/rate gate.
        dockEvents.startObserving("POWER_SUPPLY_REVERSE_PEN_CHG_STATE=");
        displays.registerDisplayListener(displayEvents, actor);
        actor.post(this::tick);
        try { charging = new PenChargingMonitor(this); }
        catch (RuntimeException error) { Log.e(TAG, "Charging feedback startup failed", error); }
    }

    private boolean awake() {
        Display display = displays == null ? null : displays.getDisplay(Display.DEFAULT_DISPLAY);
        return display != null && power != null && power.isInteractive()
                && display.getState() == Display.STATE_ON;
    }
    private static String node(String path) throws Exception {
        return new String(Files.readAllBytes(Paths.get(path)), StandardCharsets.UTF_8).trim();
    }
    private int dock() {
        try {
            String a = node("/sys/class/qcom-battery/pen_hall3");
            String b = node("/sys/class/qcom-battery/pen_hall4");
            if ((!a.equals("0") && !a.equals("1")) || (!b.equals("0") && !b.equals("1"))) return -1;
            return a.equals("0") || b.equals("0") ? 0 : 1;
        } catch (Exception error) { return -1; }
    }
    private void tick() {
        reconcile();
        actor.postDelayed(this::tick, 500);
    }
    private void requestReconcile() {
        actor.removeCallbacks(reconcileEvent);
        actor.post(reconcileEvent);
    }
    private void reconcile() {
        try {
            if (inputs == null) inputs = new PenInputLease(this);
            int currentDock = dock();
            boolean currentAwake = awake();
            if (pendingDockPairing != null) showDockPairingDialog(pendingDockPairing);
            List<BluetoothDevice> candidates = new ArrayList<>();
            if (bluetooth != null && bluetooth.isEnabled()) {
                reconcileDockPairing();
                for (BluetoothDevice device : bluetooth.getBondedDevices()) {
                    String name = device.getName();
                    if (device.isConnected() && ("Xiaomi Focus Pen".equals(name)
                            || "Xiaomi Focus Pen Pro".equals(name))) candidates.add(device);
                }
            }
            reconcileConnection(candidates, currentAwake, currentDock);
        } catch (Exception error) {
            Log.e(TAG, "Pen actor deferred", error);
            if (session != null) session.close("actor failure");
        }
    }

    /** The reverse charger identifies the physically attached peer, never a scan name. */
    private void reconcileDockPairing() {
        ChargeStatus charge = ChargeStatus.read();
        String peer = charge.docked() ? charge.address : null;
        long now = SystemClock.elapsedRealtime();
        if (peer == null || !peer.equals(dockPeer)) {
            dockPeer = peer;
            dockPeerSince = now;
            pairingRetryAt = 0;
            pairingAttempts = 0;
            return;
        }
        if (now - dockPeerSince < 2000 || pairingAttempts >= 3 || now < pairingRetryAt) return;
        StringBuilder address = new StringBuilder();
        for (int i = 0; i < peer.length(); i += 2) {
            if (i != 0) address.append(':');
            address.append(peer, i, i + 2);
        }
        BluetoothDevice device = bluetooth.getRemoteDevice(address.toString());
        if (device.isConnected() || device.getBondState() == BluetoothDevice.BOND_BONDING) return;
        pairingAttempts++;
        pairingRetryAt = now + 30000;
        if (device.getBondState() == BluetoothDevice.BOND_NONE) {
            Log.i(TAG, "Dock pairing attempt=" + pairingAttempts + " accepted="
                    + device.createBond(BluetoothDevice.TRANSPORT_LE));
        } else if (device.getBondState() == BluetoothDevice.BOND_BONDED) {
            Log.i(TAG, "Dock reconnect attempt=" + pairingAttempts + " result=" + device.connect());
        }
    }

    private void showDockPairingDialog(Intent request) {
        try {
            BluetoothDevice device = request.getParcelableExtra(
                    BluetoothDevice.EXTRA_DEVICE, BluetoothDevice.class);
            ChargeStatus charge = ChargeStatus.read();
            if (device == null || !charge.docked() || charge.address == null
                    || !charge.address.equals(dockPeer) || pairingAttempts == 0
                    || !charge.address.equals(ChargeStatus.address(device.getAddress()))
                    || device.getBondState() != BluetoothDevice.BOND_BONDING) {
                pendingDockPairing = null;
                return;
            }
            pendingDockPairing = request;
            if (!awake()) return;
            // Keep Android's real pairing variant/key and its user consent dialog.
            Intent dialog = new Intent(BluetoothDevice.ACTION_PAIRING_REQUEST)
                    .setClassName("com.android.settings",
                            "com.android.settings.bluetooth.BluetoothPairingDialog")
                    .putExtra(BluetoothDevice.EXTRA_DEVICE, device)
                    .putExtra(BluetoothDevice.EXTRA_PAIRING_VARIANT, request.getIntExtra(
                            BluetoothDevice.EXTRA_PAIRING_VARIANT, BluetoothDevice.ERROR))
                    .putExtra(BluetoothDevice.EXTRA_PAIRING_CONTEXT, request.getIntExtra(
                            BluetoothDevice.EXTRA_PAIRING_CONTEXT, BluetoothDevice.ERROR))
                    .putExtra(BluetoothDevice.EXTRA_PAIRING_KEY, request.getIntExtra(
                            BluetoothDevice.EXTRA_PAIRING_KEY, BluetoothDevice.ERROR))
                    .putExtra(BluetoothDevice.EXTRA_PAIRING_INITIATOR,
                            BluetoothDevice.EXTRA_PAIRING_INITIATOR_FOREGROUND)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivityAsUser(dialog, UserHandle.CURRENT);
            pendingDockPairing = null;
            Log.i(TAG, "Showing system pairing dialog for attached pen");
        } catch (RuntimeException error) {
            Log.w(TAG, "System pen pairing dialog unavailable", error);
        }
    }

    private boolean confirmDockPairing(Intent request) {
        if (request.getIntExtra(BluetoothDevice.EXTRA_PAIRING_VARIANT, BluetoothDevice.ERROR)
                != BluetoothDevice.PAIRING_VARIANT_CONSENT) return false;
        BluetoothDevice device = request.getParcelableExtra(
                BluetoothDevice.EXTRA_DEVICE, BluetoothDevice.class);
        ChargeStatus charge = ChargeStatus.read();
        if (device == null || !charge.docked() || charge.address == null
                || !charge.address.equals(dockPeer) || pairingAttempts == 0
                || !charge.address.equals(ChargeStatus.address(device.getAddress()))
                || device.getBondState() != BluetoothDevice.BOND_BONDING) return false;
        try {
            if (!device.setPairingConfirmation(true)) return false;
            pendingDockPairing = null;
            Log.i(TAG, "Automatically confirmed pairing for charger-identified attached pen");
            return true;
        } catch (RuntimeException error) {
            Log.w(TAG, "Dock pairing confirmation unavailable", error);
            return false;
        }
    }

    /** Consume one authoritative poll on the actor, including observed disconnects. */
    void reconcileConnection(List<BluetoothDevice> candidates, boolean currentAwake,
            int currentDock) throws Exception {
        if (currentDock != lastDock || currentAwake != lastAwake) {
            Log.i(TAG, "Observed dock=" + currentDock + " awake=" + currentAwake
                    + " uptime=" + SystemClock.uptimeMillis());
            failures = 0; retryAt = 0;
            lastDock = currentDock; lastAwake = currentAwake;
        }
        // A new physical connection gets a fresh budget even for the same MAC.
        // Only an authoritative poll can end the prior connection; repeated
        // broadcasts or GATT failures on a still-connected peer retain the cap.
        if (candidates.size() != 1) retryAddress = null;
        // Keep observing connection edges while old input restoration is pending,
        // but do not start a new GATT or native owner until it has completed.
        if (session == null && !inputs.restore()) return;
        if (session != null) {
            if (candidates.size() != 1 || !session.address().equals(candidates.get(0).getAddress())) {
                session.close("physical connection/identity changed"); return;
            }
            session.observe(currentAwake, currentDock);
            return;
        }
        if (candidates.size() != 1 || !currentAwake || currentDock < 0) return;
        BluetoothDevice device = candidates.get(0);
        if (!device.getAddress().equals(retryAddress)) {
            retryAddress = device.getAddress(); failures = 0; retryAt = 0;
        }
        if (failures >= 3 || SystemClock.uptimeMillis() < retryAt) return;
        IPenController controller = IPenController.Stub.asInterface(ServiceManager
                .getService("vendor.lineage.sheng.stylus.IPenController/default"));
        if (controller == null) return;
        session = new PenGattSession(this, actor, device, bluetooth, controller, inputs,
                displays, () -> {
                    session = null;
                    failures++;
                    retryAt = SystemClock.uptimeMillis() + Math.min(60000, 5000L << failures);
                });
        session.observe(currentAwake, currentDock);
        session.start();
    }
}
