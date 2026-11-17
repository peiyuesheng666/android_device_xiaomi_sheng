// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.pen.charge;

import java.io.FileInputStream;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/** A fresh, bounded snapshot of sheng's charger. No charger controls are written. */
public final class ChargeStatus {
    public enum State { UNKNOWN, DETACHED, NOT_CHARGING, WAITING, CHARGING, FULL, MISALIGNED, ACQUIRING }
    public final State state;
    public final int level;
    public final String address;

    private ChargeStatus(State state, int level, String address) {
        this.state = state; this.level = level; this.address = address;
    }

    public boolean docked() {
        return state != State.UNKNOWN && state != State.DETACHED;
    }

    public boolean charging() { return state == State.CHARGING; }

    public static String address(String raw) {
        if (raw == null) return null;
        String value = raw.trim().toUpperCase(Locale.ROOT);
        if (value.matches("(?:[0-9A-F]{2}:){5}[0-9A-F]{2}")) value = value.replace(":", "");
        else if (!value.matches("[0-9A-F]{1,12}")) return null;
        // The driver reports decimal 255 when it has no peer, not a short MAC.
        if (value.equals("255") || value.equals("FF")) return null;
        value = "000000000000".substring(value.length()) + value;
        return value.equals("000000000000") || value.equals("FFFFFFFFFFFF") ? null : value;
    }

    private static int number(String raw) {
        try { return Integer.parseInt(raw.trim()); }
        catch (Exception invalid) { return -1; }
    }

    public static ChargeStatus decode(String hall3, String hall4, String mode,
            String soc, String mac, String placement) {
        int a = number(hall3), b = number(hall4);
        if ((a != 0 && a != 1) || (b != 0 && b != 1)) return unknown();
        if (a == 1 && b == 1) return new ChargeStatus(State.DETACHED, -1, null);
        if (number(placement) > 0) return new ChargeStatus(State.MISALIGNED, -1, null);
        int chargingMode = number(mode);
        if (chargingMode == 0 || chargingMode == 2)
            return new ChargeStatus(State.NOT_CHARGING, -1, null);
        if (chargingMode < 0) return unknown();
        int level = number(soc);
        String peer = address(mac);
        // On this device state 4 was captured with a real 99 -> 100 charge.
        // Pairing/stopped states and SOC 255 never qualify as charging.
        if (chargingMode != 4 || level < 0 || level > 100 || peer == null)
            return new ChargeStatus(State.WAITING, -1, null);
        return new ChargeStatus(level == 100 ? State.FULL : State.CHARGING, level, peer);
    }

    public static ChargeStatus unknown() { return new ChargeStatus(State.UNKNOWN, -1, null); }

    public static ChargeStatus fromProvider(String name, int level, String peer) {
        try {
            State state = State.valueOf(name);
            if (state == State.CHARGING || state == State.FULL) {
                String identity = address(peer);
                if (identity == null || level < 0 || level > 100 || (state == State.FULL) != (level == 100)) return unknown();
                return new ChargeStatus(state, level, identity);
            }
            return new ChargeStatus(state, -1, null);
        } catch (Exception invalid) { return unknown(); }
    }

    static String node(String name) throws Exception {
        byte[] buffer = new byte[97];
        try (FileInputStream input = new FileInputStream("/sys/class/qcom-battery/" + name)) {
            int length = input.read(buffer);
            if (length == buffer.length) throw new IllegalStateException("Invalid charger node");
            // The charger returns EOF for an unset pen MAC. It is missing data,
            // not a failure to read the independent stopped/attachment state.
            if (length < 0) return "";
            return new String(buffer, 0, length, StandardCharsets.UTF_8).trim();
        }
    }

    public interface NodeReader { String read(String name) throws Exception; }

    public static ChargeStatus read() { return read(ChargeStatus::node); }

    public static ChargeStatus read(NodeReader nodes) {
        try {
            String a = nodes.read("pen_hall3"), b = nodes.read("pen_hall4");
            if ((number(a) != 0 && number(a) != 1) || (number(b) != 0 && number(b) != 1)) return unknown();
            // Undocked charger attributes can be unavailable. Hall state alone is
            // sufficient to report a removed pen and rearm the next attachment.
            if (number(a) == 1 && number(b) == 1) {
                if (!a.equals(nodes.read("pen_hall3")) || !b.equals(nodes.read("pen_hall4"))) return unknown();
                return new ChargeStatus(State.DETACHED, -1, null);
            }
            String mode = nodes.read("reverse_chg_state"), error = nodes.read("pen_place_err");
            if (number(mode) == 0 || number(mode) == 2) {
                if (!a.equals(nodes.read("pen_hall3")) || !b.equals(nodes.read("pen_hall4"))
                        || !mode.equals(nodes.read("reverse_chg_state"))) return unknown();
                return decode(a, b, mode, null, null, error);
            }
            String peer = nodes.read("pen_mac"), level = nodes.read("pen_soc");
            // Do not combine an old pen's SOC with a new attachment's identity.
            if (!a.equals(nodes.read("pen_hall3")) || !b.equals(nodes.read("pen_hall4"))
                    || !peer.equals(nodes.read("pen_mac")) || !mode.equals(nodes.read("reverse_chg_state"))) return unknown();
            return decode(a, b, mode, level, peer, error);
        } catch (Exception unavailable) { return unknown(); }
    }
}
