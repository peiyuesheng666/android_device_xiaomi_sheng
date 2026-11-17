package org.lineageos.sheng.stylus;
public final class PenInputIdentityTest {
    private static void check(boolean value) { if (!value) throw new AssertionError(); }
    public static void main(String[] args) {
        String pen = "70:61:ee:8a:6c:67";
        check(PenInputIdentity.matches(34, 0x4d80, pen, 0x4d80, pen));
        check(PenInputIdentity.matches(34, 0x3280, pen.toUpperCase(), 0x3280, pen));
        check(PenInputIdentity.matches(34, 0x5081, pen, 0x5081, pen));
        check(PenInputIdentity.matches(34, 0x3281, pen, 0x3281, pen));
        check(!PenInputIdentity.matches(0, 0, null, 0x4d80, pen)); // NVT physical pen.
        check(!PenInputIdentity.matches(34, 0x4d80, "70:61:ee:8a:6c:68", 0x4d80, pen));
        check(!PenInputIdentity.matches(34, 0x5081, pen, 0x4d80, pen));
        check(!PenInputIdentity.matches(35, 0x4d80, pen, 0x4d80, pen));
        check(!PenInputIdentity.matches(34, 0x1234, pen, 0x1234, pen));
        check(!PenInputIdentity.matches(34, 0x4d80, pen, 0x4d80, null));
        check(!PenInputIdentity.matches(34, 0x4d80, "00:00:00:00:00:00", 0x4d80, "00:00:00:00:00:00"));
        System.out.println("PASS ordinary/pro companion identity; NVT, other pens and ID reuse excluded");
    }
}
