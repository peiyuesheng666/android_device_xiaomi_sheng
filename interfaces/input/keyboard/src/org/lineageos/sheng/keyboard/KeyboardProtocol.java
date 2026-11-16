// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.keyboard;

import java.util.Arrays;

/** Wire contract shared by sheng's original keyboard HAL and accessory MCU. */
final class KeyboardProtocol {
    static final int KEYBOARD = 0x38;
    static final int MCU = 0x18;
    static final int VERSION = 0x01;
    static final int REQUEST = 0x24;
    static final int SLEEP = 0x28;
    static final int AUTH_START = 0x31;
    static final int AUTH_CHALLENGE = 0x32;
    static final int AUTH_TOKEN = 0x33;
    static final int TOUCHPAD = 0x21;
    static final int POWER = 0x25;

    private static byte[] packet(int report, int protocol, int target, int command, byte[] data) {
        byte[] packet = new byte[68];
        packet[0] = (byte) 0xaa; packet[1] = 0x42; packet[2] = 0x32;
        packet[4] = (byte) report; packet[5] = (byte) protocol;
        packet[6] = (byte) 0x80; packet[7] = (byte) target;
        packet[8] = (byte) command; packet[9] = (byte) data.length;
        System.arraycopy(data, 0, packet, 10, data.length);
        packet[10 + data.length] = sum(packet, 4, 6 + data.length);
        return packet;
    }

    static byte sum(byte[] data, int start, int count) {
        int value = 0;
        for (int i = start; i < start + count; ++i) value += data[i] & 0xff;
        return (byte) value;
    }

    static byte[] version(int target) {
        if (target != KEYBOARD && target != MCU) throw new IllegalArgumentException("target");
        return packet(0x4e, 0x30, target, VERSION, new byte[]{0});
    }

    static byte[] authStart() {
        return packet(0x4f, 0x31, KEYBOARD, AUTH_START, new byte[]{'M','I','A','U','T','H'});
    }

    static byte[] feature(int command, boolean enabled) {
        // Only the two normal feature controls used here; no reset or upgrade API.
        if (command != TOUCHPAD && command != POWER) throw new IllegalArgumentException("feature");
        return packet(0x4e, 0x31, KEYBOARD, command, new byte[]{(byte) (enabled ? 1 : 0)});
    }

    static int keyboardType(byte[] reply) {
        if (!validReply(reply) || reply[1] != 0x30 || reply[2] != KEYBOARD
                || reply[4] != VERSION || (reply[5] & 0xff) < 8) return -1;
        return reply[13] & 0xff;
    }

    static boolean hasTouchpad(int type) { return type == 16 || type == 32 || type == 33; }

    static byte[] challenge(byte[] metadata, byte[] challenge) {
        if (metadata.length != 4 || challenge.length != 16) throw new IllegalArgumentException("auth size");
        byte[] data = Arrays.copyOf(metadata, 20);
        System.arraycopy(challenge, 0, data, 4, 16);
        return packet(0x4f, 0x31, KEYBOARD, AUTH_CHALLENGE, data);
    }

    static byte[] token(byte[] token) {
        if (token.length != 16) throw new IllegalArgumentException("token size");
        return packet(0x4f, 0x31, KEYBOARD, AUTH_TOKEN, token);
    }

    static boolean validReply(byte[] reply) {
        if (reply.length < 7) return false;
        int report = reply[0] & 0xff, protocol = reply[1] & 0xff;
        int source = reply[2] & 0xff, payload = reply[5] & 0xff;
        if (report != 0x22 && report != 0x23 && report != 0x24 && report != 0x26) return false;
        if (reply[3] != (byte) 0x80 || (source != KEYBOARD && source != MCU)) return false;
        if (protocol != 0x30 && protocol != 0x31) return false;
        return payload + 7 <= reply.length && sum(reply, 0, payload + 6) == reply[payload + 6];
    }

    private KeyboardProtocol() {}
}
