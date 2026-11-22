// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.diagnostics;

import android.hardware.input.IInputManager;
import android.os.Process;
import android.os.ServiceManager;
import android.view.InputDevice;

/** Restores only the exact bonded Pro inputs owned by the interrupted diagnostic. */
public final class ShengPenInputRestoreProbe {
    public static void main(String[] args) throws Exception {
        if (Process.myUid() != 0 || args.length != 1
                || !"--restore-pro-hid".equals(args[0])) {
            throw new IllegalArgumentException("Root, --restore-pro-hid required");
        }
        IInputManager input = IInputManager.Stub.asInterface(ServiceManager.getService("input"));
        if (input == null) throw new IllegalStateException("Input service unavailable");
        int restored = 0;
        for (int id : input.getInputDeviceIds()) {
            InputDevice device = input.getInputDevice(id);
            if (device == null || device.getVendorId() != 34 || device.getProductId() != 20609
                    || !"28:CE:15:31:70:0E".equalsIgnoreCase(device.getBluetoothAddress())) continue;
            if (!device.isEnabled()) {
                input.enableInputDevice(id);
                // Native input reconfiguration is asynchronous to this Binder call.
                long deadline = android.os.SystemClock.uptimeMillis() + 5000;
                while (!input.getInputDevice(id).isEnabled()
                        && android.os.SystemClock.uptimeMillis() < deadline) {
                    Thread.sleep(100);
                }
                if (!input.getInputDevice(id).isEnabled()) {
                    throw new IllegalStateException("Owned input did not enable: " + id);
                }
                restored++;
            }
            System.out.println("OWNED_PRO_INPUT_ENABLED id=" + id
                    + " descriptor=" + device.getDescriptor());
        }
        System.out.println("RESTORED_INPUT_COUNT=" + restored);
    }
}
