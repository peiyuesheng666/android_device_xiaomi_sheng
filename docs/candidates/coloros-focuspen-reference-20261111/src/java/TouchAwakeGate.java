package com.codex.focuspen;

/** Delay touch configuration until both Android and the display report awake. */
final class TouchAwakeGate {
    private long awakeSince = -1;
    synchronized boolean ready(boolean interactive, String dpms, long elapsed) {
        if (!interactive || !"On".equals(dpms)) {
            awakeSince = -1;
            return false;
        }
        if (awakeSince < 0 || elapsed < awakeSince) awakeSince = elapsed;
        return elapsed - awakeSince >= 1000;
    }
}
