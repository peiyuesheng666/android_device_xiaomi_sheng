// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

/** Stock packet fixtures and namespace/model boundaries; no hardware acceptance. */
public final class PenProtocolOfflineTest {
    private static int checks;
    private static byte[] bytes(String hex) {
        byte[] value = new byte[hex.length() / 2];
        for (int i = 0; i < value.length; i++) {
            value[i] = (byte) Integer.parseInt(hex.substring(i * 2, i * 2 + 2), 16);
        }
        return value;
    }
    private static String hex(byte[] value) {
        StringBuilder out = new StringBuilder();
        for (byte b : value) out.append(String.format("%02x", b & 255));
        return out.toString();
    }
    private static void check(boolean valid) {
        checks++;
        if (!valid) throw new AssertionError("Stock protocol check " + checks);
    }
    private static void rejects(Runnable action) {
        try { action.run(); } catch (IllegalArgumentException expected) { checks++; return; }
        throw new AssertionError("Unverified command was accepted");
    }
    private static void packet(byte[] value, String expected) { check(hex(value).equals(expected)); }
    public static void main(String[] args) {
        check(PenModel.fromPnp(bytes("012200804d0100")) == PenModel.FOCUS);
        check(PenModel.fromPnp(bytes("01220080320100")) == PenModel.FOCUS);
        check(PenModel.fromPnp(bytes("01220081500100")) == PenModel.PRO);
        check(PenModel.fromPnp(bytes("01220081320100")) == PenModel.PRO);
        check(PenModel.FOCUS.touchType == 3 && PenModel.PRO.touchType == 8);
        check(PenModel.fromPnp(bytes("022200804d0100")) == null);
        check(PenModel.fromPnp(bytes("012200814d0100")) == null);
        check(PenModel.fromBluetoothIds(0x15d9, 0x00a3) == null);
        check(PenModel.fromPnp(null) == null);
        check(PenModel.fromPnp(bytes("012200804d")) == null);

        packet(MippProfile.parameters(bytes("001122334455"), 0, false),
                "301e0011223344550300a01e3e171a041a0300000d680000052800000d68f401");
        packet(MippProfile.parameters(bytes("001122334455"), 1, true),
                "301e0011223344550301a01e3e171a041a0100000d680000052800000d68f401");
        // Full packet captured in the physically successful Pro trial 003101.
        packet(MippProfile.parameters(bytes("38c6bd5c9887"), 255, false),
                "301e38c6bd5c988703ffa01e3e171a041a0300000d680000052800000d68f401");
        packet(MippProfile.frequency(1, 0), "310801039b6fef432800");
        packet(MippProfile.frequency(1, 1), "31080103e95bcd373c00");
        packet(MippProfile.frequency(1, 2), "31080103409cdd2c3c00");
        packet(MippProfile.frequency(1, 3), "31080103204ef7213c00");
        packet(MippProfile.voltage(1), "3203012800");
        packet(MippProfile.timestamp(0x01020304L), "330401020304");
        packet(MippProfile.timestamp(0xffffffffL), "3304ffffffff");
        packet(MippProfile.proScreenState(PenModel.PRO, true), "610101");
        packet(MippProfile.proMotionState(PenModel.PRO, 0), "620100");
        packet(MippProfile.proMotionState(PenModel.PRO, 1), "620101");
        rejects(() -> MippProfile.proMotionState(PenModel.FOCUS, 1));
        rejects(() -> MippProfile.proMotionState(PenModel.PRO, 2));
        rejects(() -> MippProfile.proScreenState(PenModel.FOCUS, true));
        rejects(() -> MippProfile.parameters(new byte[5], 1, false));
        rejects(() -> MippProfile.frequency(1, 4));
        rejects(() -> MippProfile.parameters(new byte[6], 256, false));
        rejects(() -> MippProfile.timestamp(-1));
        rejects(() -> MippProfile.timestamp(0x100000000L));
        System.out.println("PASS stock_protocol_checks=" + checks + " hardware_tested=false");
    }
}
