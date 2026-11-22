package org.lineageos.sheng.usbpower;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.hardware.usb.UsbManager;
import android.hardware.usb.UsbPort;
import android.hardware.usb.UsbPortStatus;
import android.util.Log;

/** A manifest receiver handles USB changes without a permanent background service. */
public final class UsbPowerReceiver extends BroadcastReceiver {
    private static final String CHANNEL = "usb_power";
    private static final int NOTIFICATION = 1;

    static UsbPort connectedPort(Context context) {
        UsbManager manager = context.getSystemService(UsbManager.class);
        if (manager != null) for (UsbPort port : manager.getPorts()) {
            UsbPortStatus status = port.getStatus();
            if (status != null && status.isConnected()) return port;
        }
        return null;
    }

    @Override public void onReceive(Context context, Intent intent) { update(context); }

    static void update(Context context) {
        UsbPowerProvider.notifyStateChanged(context);
        try {
            NotificationManager manager = context.getSystemService(NotificationManager.class);
            if (manager == null) return;
            UsbPort port = connectedPort(context);
            UsbPortStatus status = port == null ? null : port.getStatus();
            if (status == null || !status.isConnected()) {
                manager.cancel(NOTIFICATION);
                return;
            }
            manager.createNotificationChannel(new NotificationChannel(CHANNEL,
                    context.getString(R.string.notification_channel), NotificationManager.IMPORTANCE_LOW));
            boolean source = status.getCurrentPowerRole() == UsbPortStatus.POWER_ROLE_SOURCE;
            PendingIntent open = PendingIntent.getActivity(context, 0,
                    new Intent("android.intent.action.POWER_USAGE_SUMMARY")
                            .setPackage("com.android.settings"), PendingIntent.FLAG_IMMUTABLE
                            | PendingIntent.FLAG_UPDATE_CURRENT);
            manager.notify(NOTIFICATION, new Notification.Builder(context, CHANNEL)
                    .setSmallIcon(R.drawable.ic_usb_power)
                    .setContentTitle(context.getString(source ? R.string.notification_supplying
                            : R.string.notification_receiving))
                    .setContentText(context.getString(R.string.notification_detail))
                    .setContentIntent(open).setCategory(Notification.CATEGORY_SYSTEM)
                    .setOngoing(true).setOnlyAlertOnce(true).setShowWhen(false).build());
        } catch (RuntimeException e) {
            Log.e("ShengUsbPower", "Cannot update USB notification", e);
        }
    }
}
