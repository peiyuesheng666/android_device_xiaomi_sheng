package org.lineageos.sheng.usbpower;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.hardware.usb.UsbManager;
import android.hardware.usb.UsbPort;
import android.hardware.usb.UsbPortStatus;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.service.quicksettings.Tile;
import android.service.quicksettings.TileService;
import android.util.Log;
import android.widget.Toast;

/** Reflects the negotiated USB power role; never stores a synthetic on/off preference. */
public final class UsbPowerTileService extends TileService {
    private static final String TAG = "ShengUsbPower";
    private final Handler handler = new Handler(Looper.getMainLooper());
    private String pendingPort;
    private int pendingRole;
    private long deadline;
    private boolean listening;
    private final Runnable refresh = this::update;
    private final BroadcastReceiver receiver = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) { update(); }
    };

    @Override public void onStartListening() {
        super.onStartListening();
        if (!listening) {
            registerReceiver(receiver, new IntentFilter(UsbManager.ACTION_USB_PORT_CHANGED),
                    Context.RECEIVER_NOT_EXPORTED);
            listening = true;
        }
        update();
    }

    @Override public void onStopListening() {
        if (listening) unregisterReceiver(receiver);
        listening = false;
        handler.removeCallbacks(refresh);
        super.onStopListening();
    }

    @Override public void onDestroy() {
        if (listening) unregisterReceiver(receiver);
        listening = false;
        handler.removeCallbacksAndMessages(null);
        super.onDestroy();
    }

    private UsbPort connectedPort() {
        UsbManager manager = getSystemService(UsbManager.class);
        if (manager != null) for (UsbPort port : manager.getPorts()) {
            UsbPortStatus status = port.getStatus();
            if (status != null && status.isConnected()) return port;
        }
        return null;
    }

    @Override public void onClick() {
        super.onClick();
        if (isLocked()) { unlockAndRun(this::toggle); return; }
        toggle();
    }

    private void toggle() {
        if (pendingPort != null && SystemClock.elapsedRealtime() < deadline) return;
        pendingPort = null;
        try {
            UsbPort port = connectedPort();
            UsbPortStatus status = port == null ? null : port.getStatus();
            if (status == null || !status.isConnected()) {
                message(R.string.connect_device); update(); return;
            }
            int power = status.getCurrentPowerRole() == UsbPortStatus.POWER_ROLE_SOURCE
                    ? UsbPortStatus.POWER_ROLE_SINK : UsbPortStatus.POWER_ROLE_SOURCE;
            // Preserve USB data role, including an active ADB or DP connection.
            int data = status.getCurrentDataRole();
            if (!status.isRoleCombinationSupported(power, data)) {
                message(R.string.unsupported); update(); return;
            }
            pendingPort = port.getId();
            pendingRole = power;
            deadline = SystemClock.elapsedRealtime() + 8000;
            Log.i(TAG, "Request " + pendingPort + " power=" + power + " data=" + data);
            port.setRoles(power, data);
            update();
        } catch (RuntimeException e) {
            pendingPort = null;
            Log.e(TAG, "USB power request failed", e);
            message(R.string.failed);
            update();
        }
    }

    private void update() {
        handler.removeCallbacks(refresh);
        Tile tile = getQsTile();
        if (tile == null) return;
        tile.setLabel(getString(R.string.app_name));
        try {
            UsbPort port = connectedPort();
            UsbPortStatus status = port == null ? null : port.getStatus();
            boolean connected = status != null && status.isConnected();
            if (pendingPort != null) {
                if (!connected || !pendingPort.equals(port.getId())) {
                    pendingPort = null;
                } else if (status.getCurrentPowerRole() == pendingRole) {
                    Log.i(TAG, "Confirmed " + pendingPort + " power=" + pendingRole);
                    pendingPort = null;
                } else if (SystemClock.elapsedRealtime() >= deadline) {
                    pendingPort = null;
                    message(R.string.failed);
                }
            }
            boolean source = connected
                    && status.getCurrentPowerRole() == UsbPortStatus.POWER_ROLE_SOURCE;
            tile.setState(!connected ? Tile.STATE_UNAVAILABLE
                    : source ? Tile.STATE_ACTIVE : Tile.STATE_INACTIVE);
            tile.setSubtitle(getString(pendingPort != null ? R.string.switching
                    : !connected ? R.string.connect_device
                    : source ? R.string.supplying : R.string.receiving));
            tile.setContentDescription(tile.getLabel() + ", " + tile.getSubtitle());
            if (listening && pendingPort != null) handler.postDelayed(refresh, 300);
        } catch (RuntimeException e) {
            Log.e(TAG, "Cannot read USB power state", e);
            tile.setState(Tile.STATE_UNAVAILABLE);
            tile.setSubtitle(getString(R.string.failed));
        }
        tile.updateTile();
    }

    private void message(int resource) {
        Toast.makeText(this, resource, Toast.LENGTH_SHORT).show();
    }
}
