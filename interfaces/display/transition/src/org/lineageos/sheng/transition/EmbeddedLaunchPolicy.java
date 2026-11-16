// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.transition;

import java.util.List;

/** Keep an embedded placeholder opening from ending an unrelated task launch early. */
public final class EmbeddedLaunchPolicy {
    public static final class Change {
        public final int mode;
        public final boolean embedded;
        public final boolean stationary;
        public Change(int mode, boolean embedded, boolean stationary) {
            this.mode = mode;
            this.embedded = embedded;
            this.stationary = stationary;
        }
    }

    public static boolean shouldWait(String device, String remoteName, int type,
            int open, int change, List<Change> changes) {
        if (!"sheng".equals(device) || !"QuickstepLaunch".equals(remoteName)
                || type != open || changes.isEmpty()) return false;
        boolean embeddedOpening = false;
        for (Change item : changes) {
            if (item.embedded && item.mode == open) {
                embeddedOpening = true;
            } else if (item.mode != change || (!item.embedded && !item.stationary)) {
                // Back, another task launch, rotation and resize still interrupt normally.
                return false;
            }
        }
        return embeddedOpening;
    }
    private EmbeddedLaunchPolicy() {}
}
