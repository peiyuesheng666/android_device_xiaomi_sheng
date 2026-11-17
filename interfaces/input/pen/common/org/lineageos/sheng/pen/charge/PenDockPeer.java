package org.lineageos.sheng.pen.charge;

public final class PenDockPeer {
    private PenDockPeer() {}

    public static String read() { return read(ChargeStatus::node); }

    public static String read(ChargeStatus.NodeReader nodes) {
        try {
            String hall3 = nodes.read("pen_hall3");
            String hall4 = nodes.read("pen_hall4");
            if ((!"0".equals(hall3) && !"1".equals(hall3))
                    || (!"0".equals(hall4) && !"1".equals(hall4))
                    || ("1".equals(hall3) && "1".equals(hall4))
                    || !"0".equals(nodes.read("pen_place_err"))) return null;
            String raw = nodes.read("pen_mac");
            String peer = ChargeStatus.address(raw);
            if (peer == null || !hall3.equals(nodes.read("pen_hall3"))
                    || !hall4.equals(nodes.read("pen_hall4"))
                    || !raw.equals(nodes.read("pen_mac"))
                    || !"0".equals(nodes.read("pen_place_err"))) return null;
            return peer;
        } catch (Exception unavailable) {
            return null;
        }
    }
}
