// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.pen;

import android.Manifest;
import android.app.Activity;
import android.bluetooth.*;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.os.Binder;
import android.os.Handler;
import android.os.Looper;
import android.os.Build;
import android.os.HandlerThread;
import android.view.WindowInsetsController;
import android.provider.Settings;
import android.text.TextUtils;
import java.util.ArrayDeque;
import java.util.UUID;
import org.lineageos.sheng.pen.charge.ChargeStatus;

/** Read-only pen information. This page never initializes a pen or changes touch modes. */
public final class PenSettingsActivity extends Activity {
    public static boolean supported(Context context) {
        if(!"sheng".equals(Build.DEVICE) ||
                !context.getPackageManager().hasSystemFeature(PackageManager.FEATURE_BLUETOOTH_LE))return false;
        BluetoothManager manager=context.getSystemService(BluetoothManager.class);
        return manager!=null && manager.getAdapter()!=null;
    }
    private final Handler handler = new Handler(Looper.getMainLooper());
    private BluetoothAdapter adapter;
    private BluetoothProfile hid;
    private BluetoothGatt gatt;
    private final ArrayDeque<BluetoothGattCharacteristic> reads = new ArrayDeque<>();
    private PenPageView.Field connection, battery, firmware, software;
    private PenPageView page;
    private HandlerThread chargeThread;
    private Handler chargeWorker;
    private volatile boolean visible;
    private final Binder popupWindow = new Binder();
    private volatile boolean pageStarted;
    private boolean verified;
    private volatile int chargeGeneration;
    private ChargeStatus chargeSnapshot = ChargeStatus.unknown();
    private int penLevel = -1;
    private int connectionSummary = R.string.unknown;
    private boolean initialChargeRead = true;
    private String selectedAddress;
    private int generation;
    private Runnable queryTimeout;
    private boolean observing;
    private boolean profilePending;
    private final BroadcastReceiver changes=new BroadcastReceiver() {
        @Override public void onReceive(Context context,Intent intent) {
            if(!visible)return;
            if(checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT)!=PackageManager.PERMISSION_GRANTED) {
                closeQuery();clearInfo();setConnectionSummary(R.string.permission_needed);return;
            }
            if(hid==null)openProfile();else refresh();
        }
    };

    private static UUID uuid(String id) {
        return UUID.fromString("0000"+id+"-0000-1000-8000-00805f9b34fb");
    }
    private static boolean namedFocus(BluetoothDevice device) {
        return "Xiaomi Focus Pen".equals(device.getName()) || "Xiaomi Focus Pen Pro".equals(device.getName());
    }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);setTitle(R.string.app_name);
        if(getActionBar()!=null)getActionBar().hide();
        getWindow().setDecorFitsSystemWindows(false);
        page=new PenPageView(this);setContentView(page);
        connection=page.connection;battery=page.battery;firmware=page.firmware;software=page.software;
        page.setActions(() -> startActivity(new Intent(Settings.ACTION_BLUETOOTH_SETTINGS)),this::requestRefresh);
        boolean dark=(getResources().getConfiguration().uiMode & android.content.res.Configuration.UI_MODE_NIGHT_MASK)
                ==android.content.res.Configuration.UI_MODE_NIGHT_YES;
        WindowInsetsController bars=getWindow().getInsetsController();
        if(bars!=null)bars.setSystemBarsAppearance(dark?0:
                WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS,
                WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS);
        chargeThread=new HandlerThread("ShengPenPageCharge");chargeThread.start();
        chargeWorker=new Handler(chargeThread.getLooper());
        BluetoothManager manager=getSystemService(BluetoothManager.class);
        adapter=manager==null?null:manager.getAdapter();
    }
    @Override public void onStart() {
        super.onStart(); reportPageVisibility(true);
    }
    @Override public void onStop() {
        reportPageVisibility(false); super.onStop();
    }
    private synchronized void reportPageVisibility(boolean shown) {
        pageStarted=shown; sendPageVisibility(shown);
    }
    private synchronized void renewPageVisibility() {
        if(pageStarted)sendPageVisibility(true);
    }
    private void sendPageVisibility(boolean shown) {
        Bundle extras=new Bundle(); extras.putBinder("window",popupWindow); extras.putBoolean("visible",shown);
        try { getContentResolver().call(Uri.parse("content://org.lineageos.sheng.stylus.charging"),
                "settings_visibility",null,extras); }
        catch(RuntimeException unavailable) { /* A service restart is retried by the status reader. */ }
    }
    @Override public void onResume() {
        super.onResume();visible=true;initialChargeRead=true;
        requestRefresh();
        final int current=++chargeGeneration;chargeWorker.post(() -> pollCharge(current));
    }
    private void pollCharge(int current) {
        if(!visible || current!=chargeGeneration)return;
        ChargeStatus value=readCharge();
        handler.post(() -> {
            if(!visible || current!=chargeGeneration)return;
            initialChargeRead=false;chargeSnapshot=value;page.setCharge(value);showConnectionSummary();showBattery();
        });
        chargeWorker.postDelayed(() -> pollCharge(current),500);
    }
    private ChargeStatus readCharge() {
        // Renew after service restarts; onStart/onStop also cover visible split-screen pages.
        renewPageVisibility();
        try(Cursor data=getContentResolver().query(Uri.parse("content://org.lineageos.sheng.stylus.charging/status"),
                null,null,null,null)) {
            if(data!=null && data.moveToFirst())return ChargeStatus.fromProvider(data.getString(0),data.getInt(1),data.getString(2));
        } catch(RuntimeException unavailable) { /* The service may still be starting. */ }
        return ChargeStatus.unknown();
    }
    private void setConnectionSummary(int summary) {
        connectionSummary=summary;
        showConnectionSummary();
    }
    private void showConnectionSummary() {
        boolean pending=initialChargeRead || chargeSnapshot.state==ChargeStatus.State.ACQUIRING;
        boolean transientLabel=connectionSummary==R.string.paired || connectionSummary==R.string.not_paired
                || connectionSummary==R.string.profile_unavailable || connectionSummary==R.string.reading;
        connection.setSummary(pending && transientLabel?R.string.charge_acquiring:connectionSummary);
    }
    private void showBattery() {
        if(initialChargeRead || chargeSnapshot.state==ChargeStatus.State.ACQUIRING) {
            battery.setSummary(R.string.charge_acquiring);return;
        }
        boolean matching=selectedAddress==null || selectedAddress.equals(chargeSnapshot.address);
        int level=matching && chargeSnapshot.level>=0?chargeSnapshot.level:penLevel;
        if(level>=0)battery.setSummary(level+"%");
        else if(gatt==null)battery.setSummary(R.string.unknown);
    }
    private void requestRefresh() {
        if(checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT)!=PackageManager.PERMISSION_GRANTED) {
            closeQuery();clearInfo();setConnectionSummary(R.string.permission_needed);
            requestPermissions(new String[]{Manifest.permission.BLUETOOTH_CONNECT},1);return;
        }
        openProfile();
    }
    @Override public void onRequestPermissionsResult(int request,String[] permissions,int[] results) {
        super.onRequestPermissionsResult(request,permissions,results);
        if(visible && request==1 && results.length==1 && results[0]==PackageManager.PERMISSION_GRANTED)openProfile();
    }
    private void openProfile() {
        if(!observing) {
            IntentFilter filter=new IntentFilter(BluetoothAdapter.ACTION_STATE_CHANGED);
            filter.addAction(BluetoothDevice.ACTION_BOND_STATE_CHANGED);
            filter.addAction(BluetoothHidHost.ACTION_CONNECTION_STATE_CHANGED);
            registerReceiver(changes,filter,Context.RECEIVER_EXPORTED);observing=true;
        }
        if(adapter==null || !adapter.isEnabled()) {refresh();return;}
        if(hid!=null || profilePending) {refresh();return;}
        int current=++generation;
        profilePending=true;
        boolean requested=adapter.getProfileProxy(this,new BluetoothProfile.ServiceListener() {
            @Override public void onServiceConnected(int profile,BluetoothProfile proxy) {
                if(!visible || current!=generation) {adapter.closeProfileProxy(profile,proxy);return;}
                profilePending=false;
                hid=proxy;refresh();
            }
            @Override public void onServiceDisconnected(int profile) {
                if(visible && current==generation) {profilePending=false;hid=null;refresh();}
            }
        },BluetoothProfile.HID_HOST);
        if(!requested)profilePending=false;
        refresh();
    }
    private void clearInfo() {
        penLevel=-1;selectedAddress=null;
        battery.setSummary(initialChargeRead || chargeSnapshot.state==ChargeStatus.State.ACQUIRING
                ?R.string.charge_acquiring:R.string.unknown);firmware.setSummary(R.string.unknown);
        software.setSummary(R.string.unknown);
    }
    private void refresh() {
        closeQuery();clearInfo();
        if(checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT)!=PackageManager.PERMISSION_GRANTED) {
            setConnectionSummary(R.string.permission_needed);return;
        }
        if(adapter==null || !adapter.isEnabled()) {setConnectionSummary(R.string.bluetooth_off);return;}
        if(hid==null) {
            setConnectionSummary(profilePending?R.string.reading:R.string.profile_unavailable);return;
        }
        BluetoothDevice selected=null;
        if(hid!=null) for(BluetoothDevice device:hid.getConnectedDevices())if(namedFocus(device)) {selected=device;break;}
        if(selected==null) {
            boolean paired=false;
            for(BluetoothDevice device:adapter.getBondedDevices())if(namedFocus(device)){paired=true;break;}
            setConnectionSummary(paired?R.string.paired:R.string.not_paired);return;
        }
        setConnectionSummary(R.string.connected);
        selectedAddress=ChargeStatus.address(selected.getAddress());
        battery.setSummary(R.string.reading);firmware.setSummary(R.string.reading);
        software.setSummary(R.string.reading);
        verified=false;
        gatt=selected.connectGatt(this,false,callback,BluetoothDevice.TRANSPORT_LE);
        if(gatt==null) {closeQuery();return;}
        queryTimeout=this::closeQuery;handler.postDelayed(queryTimeout,15000);
    }
    private void addRead(BluetoothGatt client,String service,String characteristic) {
        BluetoothGattService s=client.getService(uuid(service));
        BluetoothGattCharacteristic c=s==null?null:s.getCharacteristic(uuid(characteristic));
        if(c!=null && (c.getProperties() & BluetoothGattCharacteristic.PROPERTY_READ)!=0)reads.add(c);
    }
    private void nextRead() {
        if(gatt==null)return;
        // A missing or rejected optional revision must not discard other reads.
        while(!reads.isEmpty()) {
            if(gatt.readCharacteristic(reads.peek()))return;
            reads.remove();
        }
        closeQuery();
    }
    private void closeQuery() {
        if(queryTimeout!=null)handler.removeCallbacks(queryTimeout);
        queryTimeout=null;
        reads.clear();
        BluetoothGatt previous=gatt;gatt=null;
        if(previous!=null) {previous.disconnect();previous.close();}
        if(battery!=null && TextUtils.equals(getString(R.string.reading),battery.getSummary()))battery.setSummary(R.string.unknown);
        if(firmware!=null && TextUtils.equals(getString(R.string.reading),firmware.getSummary()))firmware.setSummary(R.string.unknown);
        if(software!=null && TextUtils.equals(getString(R.string.reading),software.getSummary()))software.setSummary(R.string.unknown);
    }
    private final BluetoothGattCallback callback=new BluetoothGattCallback() {
        @Override public void onConnectionStateChange(BluetoothGatt client,int status,int state) {
            handler.post(() -> {
                if(client!=gatt || !visible)return;
                if(status==0 && state==BluetoothProfile.STATE_CONNECTED) {
                    if(!client.discoverServices())closeQuery();
                } else closeQuery();
            });
        }
        @Override public void onServicesDiscovered(BluetoothGatt client,int status) {
            handler.post(() -> {
                if(client!=gatt || !visible)return;
                if(status!=0) {closeQuery();return;}
                addRead(client,"180a","2a50");
                if(reads.isEmpty()) {closeQuery();return;}
                nextRead();
            });
        }
        @Override public void onCharacteristicRead(BluetoothGatt client,BluetoothGattCharacteristic c,byte[] bytes,int status) {
            byte[] value=bytes==null?new byte[0]:bytes.clone();
            handler.post(() -> {
                if(client!=gatt || !visible || reads.peek()!=c)return;
                reads.remove();
                if(c.getUuid().equals(uuid("2a50"))) {
                    String model=status==0?PenInfo.model(value):null;
                    verified=model!=null;
                    if(!verified){setConnectionSummary(R.string.identity_unverified);closeQuery();return;}
                    setConnectionSummary(R.string.connected);
                    page.setModel(model.replace("Xiaomi ",""));
                    addRead(client,"180f","2a19");
                    addRead(client,"180a","2a26");addRead(client,"180a","2a28");
                } else if(verified && status==0 && c.getUuid().equals(uuid("2a19"))) {
                    int level=PenInfo.battery(value);
                    if(level>=0){penLevel=level;showBattery();}
                } else if(verified && status==0 &&
                        (c.getUuid().equals(uuid("2a26")) || c.getUuid().equals(uuid("2a28")))) {
                    String revision=PenInfo.revision(value);
                    if(revision!=null) {
                        PenPageView.Field destination=c.getUuid().equals(uuid("2a26"))?firmware:software;
                        destination.setSummary(revision);
                    }
                }
                nextRead();
            });
        }
    };
    @Override public void onPause() {
        ++chargeGeneration;chargeWorker.removeCallbacksAndMessages(null);
        visible=false;++generation;profilePending=false;closeQuery();
        if(observing){unregisterReceiver(changes);observing=false;}
        if(adapter!=null && hid!=null)adapter.closeProfileProxy(BluetoothProfile.HID_HOST,hid);
        hid=null;super.onPause();
    }
    @Override public void onDestroy() {
        if(chargeThread!=null)chargeThread.quitSafely();
        super.onDestroy();
    }
}
