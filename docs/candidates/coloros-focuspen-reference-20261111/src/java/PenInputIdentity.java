package com.codex.focuspen;

import java.io.File;
import java.util.Locale;

/** Hardware-backed fallback when Bluetooth labels and the magnetic MAC are absent. */
final class PenInputIdentity {
    static final class Match {
        final String address;
        final String product;
        Match(String address, String product) { this.address = address; this.product = product; }
    }

    static String normalizeMac(String raw) {
        if (raw == null) return null;
        String hex = raw.replace(":", "").trim().toUpperCase(Locale.ROOT);
        if (!hex.matches("[0-9A-F]{12}") || hex.equals("000000000000")) return null;
        return hex.substring(0, 2) + ":" + hex.substring(2, 4) + ":"
                + hex.substring(4, 6) + ":" + hex.substring(6, 8) + ":"
                + hex.substring(8, 10) + ":" + hex.substring(10, 12);
    }

    static Match match(String bus, String vendor, String product, String uniq) {
        if (!"0005".equals(bus) || !"0022".equals(vendor)
                || !("5081".equalsIgnoreCase(product) || "4d80".equalsIgnoreCase(product))) return null;
        String address = normalizeMac(uniq);
        return address == null ? null : new Match(address, product.toLowerCase(Locale.ROOT));
    }

    static Match find(String root) {
        File[] nodes = new File(root).listFiles();
        if (nodes == null) return null;
        for (File node : nodes) {
            if (!node.getName().matches("input[0-9]+")) continue;
            String path = node.getPath() + "/";
            Match found = match(TouchNodeReader.read(path + "id/bustype"),
                    TouchNodeReader.read(path + "id/vendor"), TouchNodeReader.read(path + "id/product"),
                    TouchNodeReader.read(path + "uniq"));
            if (found != null) return found;
        }
        return null;
    }
}
