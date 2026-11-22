import android.content.Context;
import android.content.res.Resources;
import android.os.Looper;
import dalvik.system.PathClassLoader;
import java.lang.reflect.Method;

/** Read the installed launcher's capability check without starting or modifying its UI. */
public final class ShengDesktopCapabilityProbe {
    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Expected installed launcher APK");
        Looper.prepareMainLooper();
        Class<?> threadClass = Class.forName("android.app.ActivityThread");
        Object thread = threadClass.getMethod("systemMain").invoke(null);
        Context context = (Context) threadClass.getMethod("getSystemContext").invoke(thread);
        context = context.createPackageContext("com.google.android.apps.nexuslauncher", 0);
        Resources res = context.getResources();
        for (int id : new int[] {0x011101f3, 0x011101f2, 0x0111006e}) {
            System.out.println(String.format("launcher_id=0x%08x name=%s value=%s",
                    id, res.getResourceName(id), res.getBoolean(id)));
        }
        for (String name : new String[] {"config_isDesktopModeSupported",
                "config_canInternalDisplayHostDesktops"}) {
            int id = res.getIdentifier(name, "bool", "android");
            System.out.println(name + "=" + res.getBoolean(id));
        }
        ClassLoader loader = new PathClassLoader(args[0], ClassLoader.getSystemClassLoader());
        Class<?> status = loader.loadClass("com.android.wm.shell.shared.desktopmode.DesktopModeStatus");
        Method check = status.getMethod("canEnterDesktopMode", Context.class);
        System.out.println("launcher_canEnterDesktopMode=" + check.invoke(null, context));
        System.exit(0);
    }
}
