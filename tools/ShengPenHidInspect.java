// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.diagnostics;

import android.bluetooth.*;
import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import java.util.ArrayDeque;
import java.util.UUID;

/** Read-only inspection of the bonded Pro's HID report references and CCCDs. */
public final class ShengPenHidInspect extends BluetoothGattCallback {
    private static UUID uuid(String id) {
        return UUID.fromString("0000" + id + "-0000-1000-8000-00805f9b34fb");
    }
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ArrayDeque<Object> reads = new ArrayDeque<>();
    private BluetoothGatt client;
    private boolean verified, closed;
    private int optionalReadsUnverified;
    private final boolean refreshRequested = "1".equals(System.getenv("SHENG_PEN_HID_REFRESH"));
    private boolean cacheRefreshed;

    public static void main(String[] args) throws Exception {
        if (args.length != 2 || !args[0].equals("--scan")
                || !args[1].equalsIgnoreCase("28:CE:15:31:70:0E"))
            throw new IllegalArgumentException("Exact bonded Pro required");
        if (Looper.myLooper() == null) Looper.prepareMainLooper();
        Class<?> manager = Class.forName("android.os.BluetoothServiceManager");
        Class.forName("android.bluetooth.BluetoothFrameworkInitializer")
                .getMethod("setBluetoothServiceManager", manager)
                .invoke(null, manager.getConstructor().newInstance());
        Class<?> activity = Class.forName("android.app.ActivityThread");
        Context context = (Context) activity.getMethod("getSystemContext")
                .invoke(activity.getMethod("systemMain").invoke(null));
        BluetoothAdapter adapter = context.getSystemService(BluetoothManager.class).getAdapter();
        if (adapter == null || !adapter.isEnabled()) throw new IllegalStateException("Bluetooth off");
        BluetoothDevice device = adapter.getRemoteDevice(args[1]);
        if (device.getBondState() != BluetoothDevice.BOND_BONDED)
            throw new IllegalStateException("Pro is not bonded");
        ShengPenHidInspect probe = new ShengPenHidInspect();
        probe.client = device.connectGatt(context, false, probe, BluetoothDevice.TRANSPORT_LE);
        if (probe.client == null) throw new IllegalStateException("GATT rejected");
        probe.handler.postDelayed(() -> probe.finish(false, "timeout"), 45000);
        Looper.loop();
    }

    private static void log(String message) { System.out.println(message); System.out.flush(); }
    private void finish(boolean success, String reason) {
        if (closed) return;
        closed = true;
        if (client != null) { client.disconnect(); client.close(); }
        log("HID_INSPECT complete=" + success + " reason=" + reason + " writes=0"
                + " optional_reads_unverified=" + optionalReadsUnverified + " cache_refreshed=" + cacheRefreshed);
        System.exit(success ? 0 : 1);
    }
    @Override public void onConnectionStateChange(BluetoothGatt g, int status, int state) {
        handler.post(() -> {
            if (closed || g != client) return;
            if (status == 0 && state == BluetoothProfile.STATE_CONNECTED) {
                if (!g.discoverServices()) finish(false, "discovery rejected");
            } else finish(false, "connection status=" + status + " state=" + state);
        });
    }
    @Override public void onServicesDiscovered(BluetoothGatt g, int status) {
        handler.post(() -> {
            if (closed || g != client) return;
            BluetoothGattService info = g.getService(uuid("180a"));
            BluetoothGattCharacteristic pnp = info == null ? null : info.getCharacteristic(uuid("2a50"));
            if (status != 0 || pnp == null) { finish(false, "PnP unavailable"); return; }
            reads.add(pnp);
            next();
        });
    }
    private void queueHid() {
        BluetoothGattService hid = client.getService(uuid("1812"));
        if (hid == null) { finish(false, "HID service unavailable"); return; }
        for (BluetoothGattCharacteristic c : hid.getCharacteristics()) {
            log("HID characteristic=" + c.getUuid() + " instance=" + c.getInstanceId()
                    + " properties=" + c.getProperties());
            if (c.getUuid().equals(uuid("2a4e")) || c.getUuid().equals(uuid("2a4b"))
                    || c.getUuid().equals(uuid("2a4d"))) reads.add(c);
            for (BluetoothGattDescriptor d : c.getDescriptors()) {
                if (d.getUuid().equals(uuid("2908")) || d.getUuid().equals(uuid("2902"))) reads.add(d);
            }
        }
    }
    private void next() {
        if (closed) return;
        Object value = reads.peek();
        if (value == null) { finish(verified, "read-only HID inspection finished"); return; }
        boolean accepted = value instanceof BluetoothGattCharacteristic
                ? client.readCharacteristic((BluetoothGattCharacteristic) value)
                : client.readDescriptor((BluetoothGattDescriptor) value);
        if (!accepted) finish(false, "read rejected");
    }
    @Override public void onCharacteristicRead(BluetoothGatt g, BluetoothGattCharacteristic c,
            byte[] value, int status) {
        handler.post(() -> {
            if (closed || g != client || reads.peek() != c) return;
            log("READ characteristic=" + c.getUuid() + " instance=" + c.getInstanceId()
                    + " status=" + status + " hex=" + hex(value));
            if (status != 0) {
                // Some Pro firmware rejects the optional Protocol Mode read.
                // Preserve its error and still inspect report references/CCCDs;
                // an error payload must never be interpreted as boot mode.
                if ((c.getUuid().equals(uuid("2a4e")) || c.getUuid().equals(uuid("2a4d")))
                        && status == BluetoothGatt.GATT_READ_NOT_PERMITTED) {
                    log((c.getUuid().equals(uuid("2a4e")) ? "PROTOCOL_MODE_UNVERIFIED" : "REPORT_READ_UNAVAILABLE")
                            + " instance=" + c.getInstanceId() + " read_status=" + status);
                    optionalReadsUnverified++;
                    reads.remove();next();return;
                }
                finish(false, "characteristic read failed"); return;
            }
            reads.remove();
            if (c.getUuid().equals(uuid("2a50"))) {
                verified = value.length == 7 && value[0] == 1
                        && value[1] == 34 && value[2] == 0 && value[3] == (byte)0x81 && value[4] == 0x50;
                if (!verified) { finish(false, "Pro identity mismatch"); return; }
                if (refreshRequested && !cacheRefreshed) {
                    try {
                        cacheRefreshed = (Boolean)BluetoothGatt.class.getMethod("refresh").invoke(client);
                        log("EXACT_PRO_CACHE_REFRESH accepted=" + cacheRefreshed);
                    } catch (ReflectiveOperationException error) {
                        finish(false, "Exact Pro cache refresh failed: " + error); return;
                    }
                    if (!cacheRefreshed) { finish(false, "Exact Pro cache refresh rejected"); return; }
                    handler.postDelayed(() -> {
                        if (!closed && !client.discoverServices()) finish(false, "Fresh discovery rejected");
                    }, 300);
                    return;
                }
                queueHid();
            }
            next();
        });
    }
    @Override public void onDescriptorRead(BluetoothGatt g, BluetoothGattDescriptor d,
            int status, byte[] value) {
        handler.post(() -> {
            if (closed || g != client || reads.peek() != d) return;
            log("READ descriptor=" + d.getUuid() + " characteristic_instance="
                    + d.getCharacteristic().getInstanceId() + " status=" + status + " hex=" + hex(value));
            if (status != 0) {
                if (d.getUuid().equals(uuid("2902")) && status == BluetoothGatt.GATT_READ_NOT_PERMITTED) {
                    log("CCCD_STATE_UNVERIFIED characteristic_instance="
                            + d.getCharacteristic().getInstanceId() + " read_status=" + status);
                    optionalReadsUnverified++;
                    reads.remove();next();return;
                }
                finish(false, "descriptor read failed"); return;
            }
            reads.remove();
            next();
        });
    }
    private static String hex(byte[] value) {
        if (value == null) return "";
        StringBuilder result = new StringBuilder();
        for (byte b : value) result.append(String.format("%02x", b & 255));
        return result.toString();
    }
}
