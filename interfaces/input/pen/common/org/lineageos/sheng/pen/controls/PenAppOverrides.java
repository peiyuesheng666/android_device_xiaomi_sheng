package org.lineageos.sheng.pen.controls;

import java.util.Collection;
import java.util.LinkedHashSet;
import java.util.Set;

public final class PenAppOverrides {
    private PenAppOverrides() {}

    public static Set<String> read(String stored) {
        Set<String> result = new LinkedHashSet<>();
        if (stored == null || stored.length() > 65536) return result;
        for (String token : stored.split(",")) {
            String name = token.trim();
            if (name.length() <= 255 && name.matches("[A-Za-z_][A-Za-z0-9_]*(\\.[A-Za-z_][A-Za-z0-9_]*)+"))
                result.add(name);
        }
        return result;
    }

    public static String write(Collection<String> packages) {
        return String.join(",", read(String.join(",", packages)));
    }
}
