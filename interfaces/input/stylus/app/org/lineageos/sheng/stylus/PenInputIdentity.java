// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

/** Identifies only Bluetooth companion inputs belonging to the active pen. */
public final class PenInputIdentity {
    private PenInputIdentity() {}

    public static boolean matches(int vendor, int product, String address,
            int expectedProduct, String expectedAddress) {
        return PenModel.fromBluetoothIds(vendor, product) != null
                && product == expectedProduct && address != null
                && expectedAddress != null && expectedAddress.length() == 17
                && !"00:00:00:00:00:00".equals(expectedAddress)
                && expectedAddress.equalsIgnoreCase(address);
    }
}
