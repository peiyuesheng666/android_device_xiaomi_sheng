// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.diagnostics;

import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothManager;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanFilter;
import android.bluetooth.le.ScanResult;
import android.bluetooth.le.ScanSettings;
import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.os.Process;
import java.util.Collections;

/** Bounded, charger-address-filtered BLE discovery; pairing is explicitly selected. */
public final class ShengPenBleProbe {
    public static void main(String[] args) throws Exception {
        if (args.length != 2 || !(args[0].equals("--scan") || args[0].equals("--pair")))
            throw new IllegalArgumentException("--scan|--pair <charger MAC>");
        if (Process.myUid() != 0 && Process.myUid() != 1000)
            throw new IllegalStateException("Run from the authorized root or system context");
        final String address = args[1].toUpperCase();
        if (!BluetoothAdapter.checkBluetoothAddress(address))
            throw new IllegalArgumentException("Invalid charger MAC");
        if (Looper.myLooper() == null) Looper.prepareMainLooper();
        Class<?> managerType = Class.forName("android.os.BluetoothServiceManager");
        Class.forName("android.bluetooth.BluetoothFrameworkInitializer")
                .getMethod("setBluetoothServiceManager", managerType)
                .invoke(null, managerType.getConstructor().newInstance());
        Class<?> at = Class.forName("android.app.ActivityThread");
        Object thread = at.getMethod("systemMain").invoke(null);
        Context context = (Context) at.getMethod("getSystemContext").invoke(thread);
        BluetoothAdapter adapter = context.getSystemService(BluetoothManager.class).getAdapter();
        if (adapter == null || !adapter.isEnabled()) throw new IllegalStateException("Bluetooth off");
        Handler handler = new Handler(Looper.getMainLooper());
        if(args[0].equals("--scan") && "1".equals(System.getenv("SHENG_PEN_RECONNECT_HID"))) {
            ShengPenHidReconnect.start(context,adapter,address,handler);
            Looper.loop();return;
        }
        if (args[0].equals("--scan") && "1".equals(System.getenv("SHENG_PEN_INSPECT"))) {
            ShengPenGattInspect.start(context, adapter.getRemoteDevice(address), handler);
            Looper.loop();
            return;
        }
        boolean[] found = {false};
        ScanCallback callback = new ScanCallback() {
            @Override public void onScanResult(int type, ScanResult result) {
                if (!address.equalsIgnoreCase(result.getDevice().getAddress()) || found[0]) return;
                found[0] = true;
                BluetoothDevice pen = result.getDevice();
                System.out.println("Matched pen=" + pen.getAddress() + " name=" + pen.getName()
                        + " bond=" + pen.getBondState() + " rssi=" + result.getRssi()
                        + " record=" + result.getScanRecord());
                if (args[0].equals("--pair")) {
                    if (address.equalsIgnoreCase(System.getenv("SHENG_PEN_VERIFIED_MAC")))
                        try {
                            System.out.println("LE createBond accepted=" + BluetoothDevice.class
                                    .getMethod("createBond", int.class)
                                    .invoke(pen, BluetoothDevice.TRANSPORT_LE));
                        } catch (ReflectiveOperationException e) {
                            System.out.println("LE createBond failed=" + e);
                        }
                    else System.out.println("Pairing skipped: launcher did not verify charger identity");
                }
                System.out.flush();
            }
            @Override public void onScanFailed(int error) {
                System.out.println("Scan failure=" + error);
                System.out.flush();
            }
        };
        System.out.println("BLE probe ready; filtering only charger MAC " + address);
        System.out.flush();
        adapter.getBluetoothLeScanner().startScan(Collections.singletonList(
            new ScanFilter.Builder().setDeviceAddress(address).build()),
            new ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(), callback);
        handler.postDelayed(() -> {
            adapter.getBluetoothLeScanner().stopScan(callback);
            System.out.println("Probe done; matched=" + found[0] + " bond="
                    + adapter.getRemoteDevice(address).getBondState());
            System.out.flush();
            System.exit(0);
        }, 120000);
        Looper.loop();
    }
}
