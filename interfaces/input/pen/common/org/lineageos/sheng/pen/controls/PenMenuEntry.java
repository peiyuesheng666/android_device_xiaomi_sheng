// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.pen.controls;

import java.util.ArrayList;
import java.util.List;

/** Ordered user choices: known operations or explicit launcher components, never arbitrary intents. */
public final class PenMenuEntry {
    public static final int MAX_ITEMS = 6;
    public final PenControls.Action action;
    public final String component;
    private PenMenuEntry(PenControls.Action action, String component) {
        this.action = action; this.component = component;
    }
    public static PenMenuEntry operation(PenControls.Action action) {
        if (action == null || action == PenControls.Action.NONE || action == PenControls.Action.MENU)
            throw new IllegalArgumentException("Not a menu operation");
        return new PenMenuEntry(action, null);
    }
    public static PenMenuEntry application(String component) {
        if (component == null || component.length() > 512
                || !component.matches("[A-Za-z0-9_]+(?:\\.[A-Za-z0-9_]+)+/[A-Za-z0-9_.$]+"))
            throw new IllegalArgumentException("Not a launcher component");
        int slash = component.indexOf('/');
        String pkg = component.substring(0, slash), name = component.substring(slash + 1);
        if (name.startsWith(".")) name = pkg + name;
        return new PenMenuEntry(null, pkg + "/" + name);
    }
    public String encode() { return component == null ? action.name() : "app:" + component; }
    public static PenMenuEntry[] read(String stored) {
        List<PenMenuEntry> result = new ArrayList<>();
        if (stored != null && stored.length() <= 4096) for (String token : stored.split(",")) {
            try {
                PenMenuEntry item = token.startsWith("app:") ? application(token.substring(4))
                        : operation(PenControls.Action.read(token, null));
                if (!result.contains(item)) result.add(item);
                if (result.size() == MAX_ITEMS) break;
            } catch (IllegalArgumentException invalid) { /* Ignore an invalid stored item. */ }
        }
        if (result.isEmpty()) for (PenControls.Action action : PenControls.DEFAULT_MENU) result.add(operation(action));
        return result.toArray(new PenMenuEntry[0]);
    }
    public static String write(List<PenMenuEntry> items) {
        if (items.isEmpty() || items.size() > MAX_ITEMS) throw new IllegalArgumentException("Menu needs 1 to 6 items");
        StringBuilder value = new StringBuilder();
        List<PenMenuEntry> seen = new ArrayList<>();
        for (PenMenuEntry item : items) {
            if (item == null || seen.contains(item)) throw new IllegalArgumentException("Duplicate menu item");
            seen.add(item);
            if (value.length() > 0) value.append(',');
            value.append(item.encode());
        }
        return value.toString();
    }
    @Override public boolean equals(Object other) {
        return other instanceof PenMenuEntry && encode().equals(((PenMenuEntry) other).encode());
    }
    @Override public int hashCode() { return encode().hashCode(); }
}
