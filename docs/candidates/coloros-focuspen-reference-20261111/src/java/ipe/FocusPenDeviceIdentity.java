package com.codex.focuspen.ipe;

import android.bluetooth.BluetoothDevice;
import android.os.SystemClock;
import android.content.Context;
import android.content.ContentValues;
import android.util.Log;
import java.io.File;
import java.io.FileReader;
import java.util.Locale;

/** Internal name fallback; never renames a remote device or impersonates an OEM pen. */
public final class FocusPenDeviceIdentity {
    private static String cachedAddress;
    private static String cachedName;
    private static String cachedModel;
    private static long cachedUntil;
    private FocusPenDeviceIdentity() { }

    public static String nameOf(BluetoothDevice device) {
        if (device == null) return null;
        return nameForAddress(device.getName(), device.getAddress());
    }

    public static synchronized String nameForAddress(String original, String address) {
        if (original != null && !original.trim().isEmpty() && !original.startsWith("Bluetooth HID")) return original;
        if (address == null) return original;
        long now = SystemClock.elapsedRealtime();
        if (address.equalsIgnoreCase(cachedAddress) && now < cachedUntil) return cachedName;
        File[] nodes = new File("/sys/class/input").listFiles();
        if (nodes == null) return original;
        for (File node : nodes) {
            if (!node.getName().matches("input[0-9]+")) continue;
            String root = node.getPath() + "/";
            String vendor = read(root + "id/vendor");
            if (!"0005".equals(read(root + "id/bustype")) || !"0022".equals(vendor)) continue;
            String product = read(root + "id/product");
            if (!("5081".equalsIgnoreCase(product) || "4d80".equalsIgnoreCase(product))) continue;
            if (!address.equalsIgnoreCase(read(root + "uniq"))) continue;
            cachedAddress = address;
            cachedName = "5081".equalsIgnoreCase(product) ? "Xiaomi Focus Pen Pro" : "Xiaomi Focus Pen";
            cachedModel = vendor.toLowerCase(Locale.ROOT) + ":" + product.toLowerCase(Locale.ROOT);
            cachedUntil = now + 2000;
            return cachedName;
        }
        return original;
    }

    private static String read(String path) {
        try (FileReader input = new FileReader(path)) {
            StringBuilder value = new StringBuilder();
            char[] buffer = new char[128];
            int size;
            while ((size = input.read(buffer)) != -1) {
                if (size == 0 || value.length() + size > 512) return null;
                value.append(buffer, 0, size);
            }
            return value.toString().replace("\u0000", "").trim();
        } catch (Exception unavailable) { return null; }
    }

    public static Object createDeviceCard(Context context, BluetoothDevice device, boolean connected) {
        if (context == null || device == null) return null;
        String name;
        String model;
        synchronized (FocusPenDeviceIdentity.class) {
            name = nameForAddress(null, device.getAddress());
            model = cachedModel;
        }
        if (name == null) return null;
        try {
            Class<?> factory = cardFactory();
            String batteryMac = context.getSharedPreferences("local_config", 4).getString("focuspen_mac", null);
            Object battery = device.getAddress().equalsIgnoreCase(batteryMac)
                    ? factory.getMethod("f", Context.class).invoke(null, context) : new java.util.ArrayList<>();
            Object info = factory.getMethod("e", Context.class, String.class, String.class,
                    boolean.class, java.util.ArrayList.class).invoke(null, context, device.getAddress(), name, connected, battery);
            if (info == null) return null;
            info.getClass().getMethod("setName", String.class).invoke(info, name);
            info.getClass().getMethod("setModelId", String.class).invoke(info,
                    model);
            return info;
        } catch (Exception error) {
            Log.e("FocusPenDeviceIdentity", "Device Space card creation failed", error);
            return null;
        }
    }

    public static void syncDeviceSpace(Context context, BluetoothDevice device) {
        Object info = createDeviceCard(context, device, true);
        if (info == null) return;
        try {
            Class<?> managerType = Class.forName("com.oplus.mydevices.sdk.DeviceInfoManager");
            Class<?> infoType = Class.forName("com.oplus.mydevices.sdk.device.DeviceInfo");
            Object manager = managerType.getField("INSTANCE").get(null);
            Object previous = managerType.getMethod("query", String.class).invoke(manager, device.getAddress());
            managerType.getMethod(previous == null ? "add" : "update", infoType).invoke(manager, info);
            String name = nameForAddress(null, device.getAddress());
            context.getSharedPreferences("local_config", Context.MODE_PRIVATE).edit()
                    .putString("sp_key_pencil_device_name", name)
                    .putString("sp_key_pencil_bluetooth_name", name).apply();
            Log.i("FocusPenDeviceIdentity", "Device Space registration submitted: " + info);
        } catch (Exception error) {
            Log.e("FocusPenDeviceIdentity", "Device Space registration failed", error);
        }
    }

    public static void onPencilConnected(Object manager) {
        try {
            Class<?> base = manager.getClass().getSuperclass();
            java.lang.reflect.Field context = base.getDeclaredField("a");
            java.lang.reflect.Field device = base.getDeclaredField("l");
            context.setAccessible(true);
            device.setAccessible(true);
            syncDeviceSpace((Context) context.get(manager), (BluetoothDevice) device.get(manager));
        } catch (Exception error) {
            Log.e("FocusPenDeviceIdentity", "Device Space connection hook failed", error);
        }
    }

    public static boolean isDeviceSpacePen(String deviceId) {
        try {
            Class<?> type = Class.forName("com.oplus.mydevices.sdk.DeviceInfoManager");
            Object manager = type.getField("INSTANCE").get(null);
            Object info = type.getMethod("queryDeviceById", String.class).invoke(manager, deviceId);
            if (info == null) return false;
            Object model = info.getClass().getMethod("getModelId").invoke(info);
            return "0022:5081".equals(model) || "0022:4d80".equals(model);
        } catch (Exception error) { return false; }
    }

    private static Class<?> cardFactory() throws ClassNotFoundException {
        for (String name : new String[] {"l3.b", "x2.b"}) {
            try {
                Class<?> type = Class.forName(name, false, FocusPenDeviceIdentity.class.getClassLoader());
                type.getMethod("e", Context.class, String.class, String.class, boolean.class, java.util.ArrayList.class);
                return type;
            } catch (ReflectiveOperationException unavailable) { }
        }
        throw new ClassNotFoundException("IPeManager device card factory");
    }

    public static void onPreferenceWrite(Context context, ContentValues values) {
        if (context == null || values == null || !values.containsKey("pencil_sp_battery_level")) return;
        try {
            Integer level = values.getAsInteger("pencil_sp_battery_level");
            String mac = values.getAsString("focuspen_mac");
            if (level == null || level < 0 || level > 100 || nameForAddress(null, mac) == null) return;
            Class<?> type = Class.forName("com.oplus.mydevices.sdk.DeviceInfoManager");
            Object manager = type.getField("INSTANCE").get(null);
            Object info = type.getMethod("query", String.class).invoke(manager, mac);
            if (info == null) return;
            java.util.ArrayList<?> battery = (java.util.ArrayList<?>) cardFactory().getMethod("f", Context.class).invoke(null, context);
            for (Object entry : battery) entry.getClass().getMethod("setValue", int.class).invoke(entry, level);
            info.getClass().getMethod("setBatteryInfoList", java.util.List.class).invoke(info, battery);
            type.getMethod("update", Class.forName("com.oplus.mydevices.sdk.device.DeviceInfo")).invoke(manager, info);
            Log.i("FocusPenDeviceIdentity", "Device Space battery refreshed from hardware: " + level);
        } catch (Exception error) {
            Log.e("FocusPenDeviceIdentity", "Device Space battery update failed", error);
        }
    }
}
