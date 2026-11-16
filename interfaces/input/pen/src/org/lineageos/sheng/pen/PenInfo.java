// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.pen;

import java.nio.charset.StandardCharsets;

/** Parsers for the verified Bluetooth Device Information and Battery services. */
final class PenInfo {
    private PenInfo() {}

    static String model(byte[] pnp) {
        // Source 1 uses Bluetooth SIG vendor IDs. Source 2 uses USB vendor IDs;
        // no source-2 Focus Pen identity has been verified on this device.
        if (pnp == null || pnp.length != 7 || (pnp[0] & 255) != 1) return null;
        int vendor = (pnp[1] & 255) | ((pnp[2] & 255) << 8);
        int product = (pnp[3] & 255) | ((pnp[4] & 255) << 8);
        if (vendor != 34) return null;
        switch (product) {
            case 19840:
            case 12928:
                return "Xiaomi Focus Pen";
            case 20609:
            case 12929:
                return "Xiaomi Focus Pen Pro";
            default:
                return null;
        }
    }

    static int battery(byte[] value) {
        if (value == null || value.length != 1 || (value[0] & 255) > 100) return -1;
        return value[0] & 255;
    }

    static String revision(byte[] value) {
        if (value == null || value.length == 0 || value.length > 64) return null;
        String revision = new String(value, StandardCharsets.UTF_8).trim();
        // Preserve a bounded printable revision, including legitimate suffixes,
        // without displaying control characters or replacement characters.
        return revision.matches("[A-Za-z0-9][A-Za-z0-9._+ -]{0,63}") ? revision : null;
    }
}
