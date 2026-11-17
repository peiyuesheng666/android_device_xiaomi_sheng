// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

/** Small, bounded Pro accessory commands; the writing timing profile stays separate. */
public final class PenFeatureCommands {
    private PenFeatureCommands() {}
    public static int replyLength(byte[] command) {
        // OEM haptic 0x5e replies with only opcode and length, unlike settings.
        return (command[0] & 255) == 0x5e ? 0 : 1;
    }
    public static boolean accepted(byte[] command, byte[] reply) {
        int length = replyLength(command);
        return reply != null && reply.length == length + 2
                && (reply[0] & 255) == ((command[0] & 255) | 128)
                && (reply[1] & 255) == length && (length == 0 || reply[2] == 1);
    }
    public static byte[][] configure(int sensitivity, int vibration) {
        check(sensitivity, 4); check(vibration, 5);
        int down = 300 + 150 * sensitivity;
        return new byte[][] {
            {0x5f, 1, 1},
            {0x5c, 4, (byte) (down >>> 8), (byte) down, 1, 44},
            {0x5a, 1, (byte) vibration},
            {0x63, 1, 1},
        };
    }
    public static byte[] haptic(int kind, int sensitivity) {
        if (kind < 1 || kind > 4) throw new IllegalArgumentException("Unknown gesture feedback");
        check(sensitivity, 4);
        int amplitude = kind <= 2 ? 96 + 38 * sensitivity : 128;
        return new byte[] {0x5e, 2, (byte) kind, (byte) amplitude};
    }
    private static void check(int value, int maximum) {
        if (value < 0 || value > maximum) throw new IllegalArgumentException("Pen control out of range");
    }
}
