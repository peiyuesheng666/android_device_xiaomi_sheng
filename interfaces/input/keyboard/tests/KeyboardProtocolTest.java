// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.keyboard;
import java.util.Arrays;

/** Synthetic wire fixtures; never opens hardware or uses real keys. */
public final class KeyboardProtocolTest {
    private static int checks;
    private static void check(boolean condition) {
        ++checks;
        if (!condition) throw new AssertionError("check " + checks);
    }
    private static byte[] hex(String value) {
        byte[] bytes = new byte[value.length() / 2];
        for (int i = 0; i < bytes.length; ++i) bytes[i] = (byte) Integer.parseInt(value.substring(i*2, i*2+2), 16);
        return bytes;
    }
    public static void main(String[] args) {
        byte[] version = KeyboardProtocol.version(0x38);
        check(version.length == 68);
        check(Arrays.equals(Arrays.copyOf(version, 12), hex("aa4232004e30803801010038")));
        byte[] hello = KeyboardProtocol.authStart();
        check(Arrays.equals(Arrays.copyOf(hello, 17), hex("aa4232004f31803831064d494155544837")));
        for (int i = 17; i < hello.length; ++i) check(hello[i] == 0);
        // Valid response with padding, plus malformed/truncated/wrong-direction variants.
        byte[] response = new byte[16];
        System.arraycopy(hex("2231388028010135"), 0, response, 0, 8);
        check(KeyboardProtocol.validReply(response));
        for (int i = 0; i < 8; ++i) {
            check(!KeyboardProtocol.validReply(Arrays.copyOf(response, i)));
        }
        for (int i = 0; i < 8; ++i) {
            byte[] corrupt = response.clone(); corrupt[i] ^= 0x40;
            check(!KeyboardProtocol.validReply(corrupt));
        }
        byte[] malformed = response.clone(); malformed[5] = (byte) 255;
        check(!KeyboardProtocol.validReply(malformed));
        try { KeyboardProtocol.challenge(new byte[3], new byte[16]); throw new AssertionError(); }
        catch (IllegalArgumentException expected) { ++checks; }
        try { KeyboardProtocol.token(new byte[15]); throw new AssertionError(); }
        catch (IllegalArgumentException expected) { ++checks; }
        try { KeyboardProtocol.version(0x40); throw new AssertionError(); }
        catch (IllegalArgumentException expected) { ++checks; }
        check(Arrays.equals(Arrays.copyOf(KeyboardProtocol.feature(0x21, true),12),
                hex("aa4232004e3180382101015a")));
        check(Arrays.equals(Arrays.copyOf(KeyboardProtocol.feature(0x25, true),12),
                hex("aa4232004e3180382501015e")));
        try { KeyboardProtocol.feature(0x20, true); throw new AssertionError(); }
        catch (IllegalArgumentException expected) { ++checks; }
        byte[] info = new byte[32];
        System.arraycopy(hex("23303880010b41019c0e00261221000000"),0,info,0,16);
        info[17] = KeyboardProtocol.sum(info,0,17);
        check(KeyboardProtocol.keyboardType(info) == 33);
        check(KeyboardProtocol.hasTouchpad(33));
        check(KeyboardProtocol.hasTouchpad(16));
        check(KeyboardProtocol.hasTouchpad(32));
        check(!KeyboardProtocol.hasTouchpad(1));
        check(!KeyboardProtocol.hasTouchpad(-1));
        info[5] = 5;
        info[11] = KeyboardProtocol.sum(info,0,11);
        check(KeyboardProtocol.keyboardType(info) == -1);
        System.out.println("PASS " + checks + " keyboard wire checks");
    }
}
