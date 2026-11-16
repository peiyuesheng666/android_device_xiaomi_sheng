// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

/** sheng's reviewed stock 32-byte timing profile, shared by Focus and Pro. */
public final class MippProfile {
    private MippProfile() {}

    public static byte[] parameters(byte[] address, int id, boolean second) {
        if (address == null || address.length != 6) {
            throw new IllegalArgumentException("Local Bluetooth address must have six bytes");
        }
        checkId(id);
        byte[] result = new byte[32];
        result[0] = 0x30;
        result[1] = 0x1e;
        System.arraycopy(address, 0, result, 2, 6);
        result[8] = 3;
        result[9] = (byte) id;
        byte[] basic = {(byte) 0xa0, 0x1e, 0x3e, 0x17, 0x1a, 4, 0x1a};
        System.arraycopy(basic, 0, result, 10, 7);
        result[17] = (byte) (second ? 1 : 3);
        byte[] timing = {0, 0, 0x0d, 0x68, 0, 0, 5, 0x28, 0, 0, 0x0d, 0x68};
        System.arraycopy(timing, 0, result, 18, 12);
        result[30] = (byte) 0xf4;
        result[31] = 1;
        return result;
    }

    public static byte[] frequency(int id, int index) {
        checkId(id);
        byte[][] values = {{(byte) 0x9b, 0x6f, (byte) 0xef, 0x43},
                {(byte) 0xe9, 0x5b, (byte) 0xcd, 0x37},
                {0x40, (byte) 0x9c, (byte) 0xdd, 0x2c},
                {0x20, 0x4e, (byte) 0xf7, 0x21}};
        if (index < 0 || index >= values.length) {
            throw new IllegalArgumentException("Unsupported pen frequency");
        }
        byte[] result = {0x31, 8, (byte) id, 3, 0, 0, 0, 0,
                (byte) (index == 0 ? 40 : 60), 0};
        System.arraycopy(values[index], 0, result, 4, 4);
        return result;
    }

    public static byte[] voltage(int id) {
        checkId(id);
        return new byte[] {0x32, 3, (byte) id, 40, 0};
    }

    public static byte[] timestamp(long seconds) {
        if (seconds < 0 || seconds > 0xffffffffL) {
            throw new IllegalArgumentException("Timestamp outside the stock unsigned-32 ABI");
        }
        return new byte[] {0x33, 4, (byte) (seconds >>> 24), (byte) (seconds >>> 16),
                (byte) (seconds >>> 8), (byte) seconds};
    }

    public static byte[] proScreenState(PenModel model, boolean on) {
        if (model != PenModel.PRO) {
            throw new IllegalArgumentException("Ordinary Focus Pen has no Pro screen command");
        }
        return new byte[] {0x61, 1, (byte) (on ? 1 : 0)};
    }

    /** Stock MIPP_PEN_STATE 0x35 -> worker 2033 -> s2/t2 packets. */
    public static byte[] proMotionState(PenModel model, int state) {
        if (model != PenModel.PRO || (state != 0 && state != 1)) {
            throw new IllegalArgumentException("Unsupported Pro motion state");
        }
        return new byte[] {0x62, 1, (byte) state};
    }

    private static void checkId(int id) {
        if (id < 0 || id > 255) throw new IllegalArgumentException("Pen ID outside byte ABI");
    }
}
