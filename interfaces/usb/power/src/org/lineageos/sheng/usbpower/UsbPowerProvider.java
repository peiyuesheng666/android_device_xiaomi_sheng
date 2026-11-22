package org.lineageos.sheng.usbpower;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.hardware.usb.UsbPort;
import android.hardware.usb.UsbPortStatus;
import android.net.Uri;
import android.os.Bundle;
import android.os.SystemClock;
import android.util.Log;
import java.util.ArrayList;

/** SettingsLib EntriesProvider wire protocol; Settings renders its own native switch. */
public final class UsbPowerProvider extends ContentProvider {
    static final String AUTHORITY = "org.lineageos.sheng.usbpower.settings";
    private static final String KEY = "sheng_usb_power";
    private static final String PREFIX = "com.android.settings.";

    @Override public boolean onCreate() { return true; }

    static void notifyStateChanged(Context context) {
        for (String method : new String[] {"isChecked", "getDynamicSummary"}) {
            context.getContentResolver().notifyChange(Uri.parse("content://" + AUTHORITY
                    + "/" + method + "/" + KEY), null);
        }
    }

    @Override public Bundle call(String method, String arg, Bundle extras) {
        getContext().enforceCallingOrSelfPermission("android.permission.MANAGE_USB",
                "USB power controls require MANAGE_USB");
        Bundle result = new Bundle();
        String key = extras == null ? null : extras.getString(PREFIX + "keyhint");
        if ("getEntryData".equals(method) || "getSwitchData".equals(method)) {
            Bundle entry = new Bundle();
            entry.putString(PREFIX + "category", "com.android.settings.category.ia.battery");
            entry.putString(PREFIX + "keyhint", KEY);
            entry.putString(PREFIX + "title", getContext().getString(R.string.battery_switch_title));
            entry.putString(PREFIX + "group_key", "percentage_category");
            entry.putString(PREFIX + "switch_uri", "content://" + AUTHORITY);
            entry.putString(PREFIX + "summary_uri", "content://" + AUTHORITY);
            // No icon, activity, pending intent, or order override: append after percentage.
            if (KEY.equals(key)) return entry;
            ArrayList<Bundle> entries = new ArrayList<>();
            entries.add(entry);
            result.putParcelableArrayList("entry_data", entries);
            result.putParcelableArrayList("switch_data", entries);
            return result;
        }
        if (!KEY.equals(key)) return null;
        try {
            UsbPort port = UsbPowerReceiver.connectedPort(getContext());
            UsbPortStatus status = port == null ? null : port.getStatus();
            boolean connected = status != null && status.isConnected();
            boolean source = connected && status.getCurrentPowerRole() == UsbPortStatus.POWER_ROLE_SOURCE;
            if ("isChecked".equals(method)) result.putBoolean("checked_state", source);
            else if ("getDynamicSummary".equals(method)) result.putString(PREFIX + "summary",
                    getContext().getString(!connected ? R.string.connect_device
                            : source ? R.string.supplying : R.string.receiving));
            else if ("onCheckedChanged".equals(method)) {
                boolean enabled = extras.getBoolean("checked_state");
                int power = enabled ? UsbPortStatus.POWER_ROLE_SOURCE : UsbPortStatus.POWER_ROLE_SINK;
                boolean success = false;
                if (connected) {
                    int data = status.getCurrentDataRole();
                    // Non-PD peers may only allow paired source/host and sink/device roles.
                    if (!status.isRoleCombinationSupported(power, data)) data = enabled
                            ? UsbPortStatus.DATA_ROLE_HOST : UsbPortStatus.DATA_ROLE_DEVICE;
                    if (status.isRoleCombinationSupported(power, data)) {
                        Log.i("ShengUsbPower", "Battery switch request " + port.getId()
                                + " power=" + power + " data=" + data);
                        port.setRoles(power, data);
                        long deadline = SystemClock.elapsedRealtime() + 8000;
                        // Settings calls on a worker thread; never report a request as success.
                        do {
                            status = port.getStatus();
                            if (status == null || !status.isConnected()) break;
                            if (status.getCurrentPowerRole() == power) { success = true; break; }
                            SystemClock.sleep(200);
                        } while (SystemClock.elapsedRealtime() < deadline);
                    }
                }
                result.putBoolean("set_checked_error", !success);
                if (!success) result.putString("set_checked_error_message",
                        getContext().getString(connected ? R.string.failed : R.string.connect_device));
                Log.i("ShengUsbPower", "Battery switch confirmed=" + success);
                UsbPowerReceiver.update(getContext());
            } else return null;
        } catch (RuntimeException e) {
            Log.e("ShengUsbPower", "Battery switch failed", e);
            result.putBoolean("set_checked_error", true);
            result.putString("set_checked_error_message", getContext().getString(R.string.failed));
        }
        return result;
    }

    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] args,
            String order) { throw new UnsupportedOperationException(); }
    @Override public String getType(Uri uri) { return null; }
    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException(); }
    @Override public int delete(Uri uri, String selection, String[] args) { throw new UnsupportedOperationException(); }
    @Override public int update(Uri uri, ContentValues values, String selection, String[] args) { throw new UnsupportedOperationException(); }
}
