package org.lineageos.sheng.stylus;

import java.util.HashMap;
import java.util.Map;
import org.lineageos.sheng.pen.charge.ChargeStatus;
import org.lineageos.sheng.pen.charge.PenDockPeer;

public final class PenDockPeerTest {
    private static int checks;

    private static void check(boolean condition) {
        checks++;
        if (!condition) throw new AssertionError("dock peer check " + checks);
    }

    private static Map<String, String> nodes() {
        Map<String, String> nodes = new HashMap<>();
        nodes.put("pen_hall3", "0");
        nodes.put("pen_hall4", "1");
        nodes.put("pen_place_err", "0");
        nodes.put("pen_mac", "28ce1531700e");
        return nodes;
    }

    public static void main(String[] arguments) {
        Map<String, String> nodes = nodes();
        check("28CE1531700E".equals(PenDockPeer.read(name -> {
            if (!nodes.containsKey(name)) throw new AssertionError("Pairing depends on battery state: " + name);
            return nodes.get(name);
        })));
        nodes.put("reverse_chg_state", "2");
        nodes.put("pen_soc", "255");
        check(ChargeStatus.read(nodes::get).state == ChargeStatus.State.NOT_CHARGING);
        check(ChargeStatus.read(nodes::get).address == null);
        check("28CE1531700E".equals(PenDockPeer.read(nodes::get)));
        for (String invalid : new String[]{"", "255", "ff", "000000000000", "ffffffffffff", "broken"}) {
            nodes.put("pen_mac", invalid);
            check(PenDockPeer.read(nodes::get) == null);
        }
        nodes.put("pen_mac", "28ce1531700e");
        for (String invalid : new String[]{"", "2", "-1", "255"}) {
            nodes.put("pen_hall3", invalid);
            check(PenDockPeer.read(nodes::get) == null);
        }
        nodes.put("pen_hall3", "1");
        check(PenDockPeer.read(nodes::get) == null);
        nodes.put("pen_hall4", "0");
        check("28CE1531700E".equals(PenDockPeer.read(nodes::get)));
        nodes.put("pen_place_err", "1");
        check(PenDockPeer.read(nodes::get) == null);
        nodes.put("pen_place_err", "0");
        int[] macReads = {0};
        check(PenDockPeer.read(name -> name.equals("pen_mac") && macReads[0]++ > 0
                ? "28ce1531700f" : nodes.get(name)) == null);
        int[] hallReads = {0};
        check(PenDockPeer.read(name -> name.equals("pen_hall4") && hallReads[0]++ > 0
                ? "1" : nodes.get(name)) == null);
        int[] placementReads = {0};
        check(PenDockPeer.read(name -> name.equals("pen_place_err") && placementReads[0]++ > 0
                ? "1" : nodes.get(name)) == null);
        check(PenDockPeer.read(name -> { throw new java.io.IOException("unavailable"); }) == null);
        System.out.println("Dock peer checks passed: " + checks);
    }
}
