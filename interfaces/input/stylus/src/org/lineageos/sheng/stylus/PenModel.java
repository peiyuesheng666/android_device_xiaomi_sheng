// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

/** Focus generations in the stock Bluetooth SIG vendor namespace. */
public enum PenModel {
    FOCUS(3), PRO(8);

    public final int touchType;
    PenModel(int type) { touchType = type; }

    public static PenModel fromPnp(byte[] value) {
        // USB vendor IDs (source 2) are a different namespace. Do not identify
        // an accessory by its name or reuse Bluetooth vendor 34 in that space.
        if (value == null || value.length != 7 || value[0] != 1) return null;
        int vendor = (value[1] & 255) | ((value[2] & 255) << 8);
        int product = (value[3] & 255) | ((value[4] & 255) << 8);
        return fromBluetoothIds(vendor, product);
    }

    public static PenModel fromBluetoothIds(int vendor, int product) {
        if (vendor != 34) return null;
        switch (product) {
            case 0x4d80:
            case 0x3280: return FOCUS;
            case 0x5081:
            case 0x3281: return PRO;
            default: return null;
        }
    }
}
