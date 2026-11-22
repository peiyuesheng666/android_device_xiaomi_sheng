// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.diagnostics;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.os.Process;
import org.lineageos.sheng.stylus.DisplayRateLease;

/** Bounded display request only: no Bluetooth, controller or Settings writes. */
public final class ShengPenDisplayVoteProbe {
    public static void main(String[] args) throws Exception {
        if (args.length != 1 || !args[0].equals("--120hz") || Process.myUid() != 1000) {
            throw new IllegalArgumentException("System UID, --120hz required");
        }
        String duration = System.getenv("SHENG_PEN_DISPLAY_VOTE_SECONDS");
        int seconds = duration == null ? 15 : Integer.parseInt(duration);
        if (seconds < 15 || seconds > 900) {
            throw new IllegalArgumentException("Display trial must be bounded to 15..900 seconds");
        }
        Looper.prepareMainLooper();
        Class<?> activityThread = Class.forName("android.app.ActivityThread");
        Object thread = activityThread.getMethod("systemMain").invoke(null);
        Context context = (Context) activityThread.getMethod("getSystemContext").invoke(thread);
        DisplayRateLease lease = new DisplayRateLease(context);
        lease.acquire(120);
        System.out.println("DISPLAY_VOTE_ACQUIRED requested=120 settings_writes=0 seconds=" + seconds);
        System.out.flush();
        new Handler(Looper.getMainLooper()).postDelayed(() -> {
            try {
                lease.close();
                System.out.println("DISPLAY_VOTE_RELEASED settings_writes=0");
                System.exit(0);
            } catch (Exception failure) {
                failure.printStackTrace();
                System.exit(1);
            }
        }, seconds * 1000L);
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            try { lease.close(); } catch (Exception failure) { failure.printStackTrace(); }
        }));
        Looper.loop();
    }
}
