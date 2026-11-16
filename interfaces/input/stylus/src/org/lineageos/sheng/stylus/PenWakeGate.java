// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.stylus;

/** Keep the real screen-on settling interval independent of a temporary display vote. */
final class PenWakeGate {
    private long awakeSince = -1;
    void observe(boolean awake, long uptime) {
        if (!awake || uptime < 0) { awakeSince = -1; return; }
        if (awakeSince < 0 || uptime < awakeSince) awakeSince = uptime;
    }
    boolean ready(boolean awake, boolean eligible, long uptime) {
        observe(awake, uptime);
        return awake && eligible && awakeSince >= 0 && uptime - awakeSince >= 1000;
    }
}
