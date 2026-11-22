// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.diagnostics;

import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothProfile;
import android.content.Context;
import android.os.Handler;

/** Explicit diagnostic reconnect of the already verified Pro only; no global BT toggle. */
final class ShengPenHidReconnect implements BluetoothProfile.ServiceListener {
    private static final int HID_HOST=4;
    private final BluetoothAdapter adapter;
    private final BluetoothDevice pen;
    private final Handler handler;
    private BluetoothProfile profile;
    private boolean connecting,finished;
    private int lastState=-1;
    private final long deadline=android.os.SystemClock.uptimeMillis()+45000;

    private ShengPenHidReconnect(BluetoothAdapter adapter,BluetoothDevice pen,Handler handler) {
        this.adapter=adapter;this.pen=pen;this.handler=handler;
    }
    static void start(Context context,BluetoothAdapter adapter,String address,Handler handler) {
        BluetoothDevice pen=adapter.getRemoteDevice(address);
        if(!"28:CE:15:31:70:0E".equalsIgnoreCase(address) ||
                !"Xiaomi Focus Pen Pro".equals(pen.getName()) || pen.getBondState()!=BluetoothDevice.BOND_BONDED)
            throw new IllegalStateException("Reconnect is restricted to the verified, bonded Pro");
        ShengPenHidReconnect probe=new ShengPenHidReconnect(adapter,pen,handler);
        if(!adapter.getProfileProxy(context,probe,HID_HOST))probe.finish(false,"HID proxy rejected");
        handler.postDelayed(() -> probe.finish(false,"HID proxy/reconnect timeout"),45000);
    }
    private void log(String value) {System.out.println(value);System.out.flush();}
    private boolean operation(String name) {
        try {
            boolean accepted=(Boolean)profile.getClass().getMethod(name,BluetoothDevice.class).invoke(profile,pen);
            log("HID "+name+" accepted="+accepted);return accepted;
        } catch(ReflectiveOperationException error) {log("HID operation failed="+error);return false;}
    }
    @Override public void onServiceConnected(int type,BluetoothProfile service) {
        handler.post(() -> {
            if(finished){adapter.closeProfileProxy(type,service);return;}
            profile=service;
            if(profile.getConnectionState(pen)==BluetoothProfile.STATE_DISCONNECTED)connect();
            else if(!operation("disconnect"))finish(false,"HID disconnect rejected");
            poll();
        });
    }
    @Override public void onServiceDisconnected(int type) {
        handler.post(() -> finish(false,"HID service disconnected"));
    }
    private void connect() {
        connecting=true;
        if(!operation("connect"))finish(false,"HID connect rejected");
    }
    private void poll() {
        if(finished)return;
        int state=profile.getConnectionState(pen);
        if(state!=lastState){lastState=state;log("HID state="+state);}
        if(!connecting && state==BluetoothProfile.STATE_DISCONNECTED) {
            // Allow the ACL and UHID removal to complete before starting a new session.
            connecting=true;
            handler.postDelayed(() -> {if(!finished)connect();},1500);
        } else if(connecting && state==BluetoothProfile.STATE_CONNECTED) {
            handler.postDelayed(() -> finish(true,"HID reconnected"),1500);return;
        }
        if(android.os.SystemClock.uptimeMillis()>=deadline){finish(false,"HID reconnect timeout");return;}
        handler.postDelayed(this::poll,200);
    }
    private void finish(boolean success,String reason) {
        if(finished)return;finished=true;
        if(profile!=null)adapter.closeProfileProxy(HID_HOST,profile);
        log(reason+" success="+success);System.exit(success?0:1);
    }
}
