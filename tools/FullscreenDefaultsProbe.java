// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.displaydefaults;

import android.app.AppGlobals;
import android.content.Context;
import android.content.Intent;
import android.content.pm.IPackageManager;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.os.Process;
import android.os.ServiceManager;
import com.android.internal.compat.IPlatformCompat;
import java.util.LinkedHashSet;
import java.util.Set;

/** Root-only device test of the actual production policy; not an APK component. */
public final class FullscreenDefaultsProbe {
    public static void main(String[] args) throws Exception {
        if (Process.myUid() != 0) throw new SecurityException("Root diagnostic only");
        IPackageManager pm = AppGlobals.getPackageManager();
        Set<String> packages = new LinkedHashSet<>();
        Intent launcher = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER);
        for (Object result : pm.queryIntentActivities(launcher, null,
                PackageManager.MATCH_DIRECT_BOOT_AWARE | PackageManager.MATCH_DIRECT_BOOT_UNAWARE,
                0).getList()) packages.add(((ResolveInfo) result).activityInfo.packageName);
        for (String name : packages)
            System.out.println("BEFORE " + name + " " + pm.getUserMinAspectRatio(name, 0));
        if (args.length == 1 && "apply".equals(args[0])) {
            IPlatformCompat service = IPlatformCompat.Stub.asInterface(
                    ServiceManager.getService(Context.PLATFORM_COMPAT_SERVICE));
            int applied = DefaultFullscreenReceiver.applyDefaults(service, packages);
            if (applied != packages.size()) throw new IllegalStateException("Incomplete defaults");
            System.out.println("APPLIED " + applied);
        }
        for (String name : packages)
            System.out.println("AFTER " + name + " " + pm.getUserMinAspectRatio(name, 0));
    }
}
