// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.pen.controls;

import android.content.ComponentName;
import android.content.Context;
import android.content.pm.LauncherActivityInfo;
import android.content.pm.LauncherApps;
import android.os.UserHandle;
import java.text.Collator;
import java.util.ArrayList;
import java.util.List;

/** Resolve against the selected Android user's launchable activities, including enabled state. */
public final class PenMenuApps {
    private PenMenuApps() {}
    public static List<LauncherActivityInfo> list(Context context, int user) {
        LauncherApps launcher = context.getSystemService(LauncherApps.class);
        List<LauncherActivityInfo> result = new ArrayList<>();
        if (launcher != null) for (LauncherActivityInfo info : launcher.getActivityList(null, UserHandle.of(user))) {
            if (launcher.isActivityEnabled(info.getComponentName(), UserHandle.of(user))) result.add(info);
        }
        Collator order = Collator.getInstance();
        result.sort((a,b) -> order.compare(a.getLabel().toString(), b.getLabel().toString()));
        return result;
    }
    public static LauncherActivityInfo resolve(Context context, PenMenuEntry item, int user) {
        if (item.component == null) return null;
        ComponentName component = ComponentName.unflattenFromString(item.component);
        LauncherApps launcher = context.getSystemService(LauncherApps.class);
        if (component == null || launcher == null || !launcher.isActivityEnabled(component, UserHandle.of(user))) return null;
        for (LauncherActivityInfo info : launcher.getActivityList(component.getPackageName(), UserHandle.of(user)))
            if (component.equals(info.getComponentName())) return info;
        return null;
    }
    public static String title(Context context, PenMenuEntry item, int user, boolean chinese) {
        if (item.action != null) return item.action.title(chinese);
        LauncherActivityInfo info = resolve(context, item, user);
        return info == null ? (chinese ? "应用不可用" : "App unavailable") : info.getLabel().toString();
    }
    public static void launch(Context context, PenMenuEntry item, int user) {
        LauncherActivityInfo info = resolve(context, item, user);
        if (info == null) throw new IllegalStateException("Selected launcher activity is unavailable");
        context.getSystemService(LauncherApps.class).startMainActivity(info.getComponentName(), UserHandle.of(user), null, null);
    }
}
