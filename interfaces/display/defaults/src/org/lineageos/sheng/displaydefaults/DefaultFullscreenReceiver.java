// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.displaydefaults;

import android.app.compat.PackageOverride;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.os.Build;
import android.os.RemoteException;
import android.os.ServiceManager;
import android.util.Log;

import java.util.HashSet;
import java.util.Set;
import java.util.Collections;

import com.android.internal.compat.CompatibilityOverrideConfig;
import com.android.internal.compat.IPlatformCompat;

/** Enables the platform OEM fullscreen default; explicit user aspect ratios still take precedence. */
public final class DefaultFullscreenReceiver extends BroadcastReceiver {
    private static final String TAG = "ShengAppDefaults";
    private static final String APPLY = "org.lineageos.sheng.action.APPLY_APP_DEFAULTS";
    private static final long FULLSCREEN_DEFAULT = 310816437L;

    @Override public void onReceive(Context context, Intent intent) {
        if (!"sheng".equals(Build.DEVICE)) return;
        String action = intent.getAction();
        if (!Intent.ACTION_BOOT_COMPLETED.equals(action)
                && !Intent.ACTION_LOCKED_BOOT_COMPLETED.equals(action)
                && !Intent.ACTION_USER_INITIALIZE.equals(action)
                && !Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)
                && !Intent.ACTION_PACKAGE_ADDED.equals(action) && !APPLY.equals(action)) return;
        PendingResult pending = goAsync();
        new Thread(() -> {
            try {
                PackageManager pm = context.getPackageManager();
                Set<String> packages = new HashSet<>();
                if (Intent.ACTION_PACKAGE_ADDED.equals(action)) {
                    String name = intent.getData() == null ? null
                            : intent.getData().getSchemeSpecificPart();
                    if (name != null && pm.getLaunchIntentForPackage(name) != null)
                        packages.add(name);
                } else {
                    Intent launcher = new Intent(Intent.ACTION_MAIN)
                            .addCategory(Intent.CATEGORY_LAUNCHER);
                    for (ResolveInfo info : pm.queryIntentActivities(launcher,
                            PackageManager.MATCH_DIRECT_BOOT_AWARE
                                    | PackageManager.MATCH_DIRECT_BOOT_UNAWARE))
                        if (info.activityInfo != null) packages.add(info.activityInfo.packageName);
                }
                IPlatformCompat service = IPlatformCompat.Stub.asInterface(
                        ServiceManager.getService(Context.PLATFORM_COMPAT_SERVICE));
                if (service == null) throw new IllegalStateException("Platform compat unavailable");
                applyDefaults(service, packages);
            } catch (RuntimeException failure) {
                Log.e(TAG, "Could not apply fullscreen defaults", failure);
            } finally {
                pending.finish();
            }
        }, "ShengAppDefaults").start();
    }

    static int applyDefaults(IPlatformCompat service, Set<String> packages) {
        CompatibilityOverrideConfig defaults = new CompatibilityOverrideConfig(
                Collections.singletonMap(FULLSCREEN_DEFAULT,
                        new PackageOverride.Builder().setEnabled(true).build()));
        int changed = 0;
        for (String name : packages) {
            try {
                // An OEM policy, not a fabricated user selection. Explicit
                // "app default"/aspect ratio choices remain effective.
                service.putOverridesOnReleaseBuilds(defaults, name);
                Log.i(TAG, "Enabled fullscreen default for " + name);
                changed++;
            } catch (RemoteException | RuntimeException failure) {
                Log.w(TAG, "Could not initialize " + name, failure);
            }
        }
        Log.i(TAG, "Fullscreen defaults: " + changed + " updated, "
                + packages.size() + " launchable packages checked");
        return changed;
    }
}
