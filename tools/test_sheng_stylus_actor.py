#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise the actual GATT actor with a deterministic Android callback harness.

This tests asynchronous ownership/ordering, not Android framework behavior,
SELinux, radio transport, input journal persistence, or physical handwriting.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--power-lifecycle', action='store_true', default=True,
                    help='Compatibility flag; power lifecycle checks run by default')
args = parser.parse_args()

SOURCE = Path(__file__).resolve().parents[1]/'interfaces/input/stylus'
ROM = Path(os.environ.get('SHENG_ROM_ROOT', '/root/sheng-lineage/lineage-24.0'))
ROOT = SOURCE.parents[5]/'reports/device/20261114-stylus-service'
ROOT.mkdir(parents=True, exist_ok=True)
WORK = Path(tempfile.mkdtemp(prefix='actor-test-', dir=ROOT))
os.environ.update(LANG='C.UTF-8', LC_ALL='C.UTF-8')
fixtures = {
'org/lineageos/sheng/stylus/PenChargingMonitor.java': '''package org.lineageos.sheng.stylus;
// The separate read-only UI is compiled against Android by the UI builder.
class PenChargingMonitor { PenChargingMonitor(android.content.Context context){} }
''',
'android/os/SystemClock.java': '''package android.os;
public class SystemClock { public static long now; public static long uptimeMillis(){return now;} public static long elapsedRealtime(){return now;} }
''',
'android/os/Binder.java': 'package android.os; public class Binder {}',
'android/os/Handler.java': '''package android.os;
import java.util.*;
public class Handler {
 public Handler(){} public Handler(Object looper){}
 private static class Task { Runnable run; long at, order; Task(Runnable r,long t,long o){run=r;at=t;order=o;} }
 private final List<Task> tasks=new ArrayList<>(); private long order;
 public void post(Runnable r){postDelayed(r,0);}
 public void postDelayed(Runnable r,long ms){tasks.add(new Task(r,SystemClock.now+ms,order++));}
 public void removeCallbacks(Runnable r){tasks.removeIf(t->t.run==r);}
 public void advance(long ms){long target=SystemClock.now+ms; int budget=10000;
  while(true){ Task best=null; for(Task t:tasks) if(t.at<=target && (best==null || t.at<best.at || t.at==best.at && t.order<best.order))best=t;
   if(best==null)break; if(--budget==0)throw new AssertionError("callback loop"); tasks.remove(best); SystemClock.now=best.at; best.run.run(); }
  SystemClock.now=target;
 }
}
''',
'android/content/Context.java': '''package android.content;
public class Context {public static final int RECEIVER_NOT_EXPORTED=4,RECEIVER_EXPORTED=2;
 public <T> T getSystemService(Class<T> type){return null;}
 public Intent registerReceiver(BroadcastReceiver receiver,IntentFilter filter,int flags){return null;}
 public Intent registerReceiver(BroadcastReceiver receiver,IntentFilter filter,String permission,android.os.Handler handler,int flags){return null;}
 public void startActivityAsUser(Intent intent,android.os.UserHandle user){}}
''',
'android/app/Application.java': 'package android.app; public class Application extends android.content.Context {public void onCreate(){}}',
'android/content/Intent.java': '''package android.content;
public class Intent {public static final String ACTION_SCREEN_ON="on",ACTION_SCREEN_OFF="off";
 public static final int FLAG_ACTIVITY_NEW_TASK=0x10000000;
 private final java.util.Map<String,Object> extras=new java.util.HashMap<>();
 public Intent(){} public Intent(String action){}
 public Intent setClassName(String pkg,String name){return this;}public Intent addFlags(int flags){return this;}
 public Intent putExtra(String key,Object value){extras.put(key,value);return this;}
 public int getIntExtra(String key,int fallback){return extras.get(key) instanceof Integer?(Integer)extras.get(key):fallback;}
 public <T> T getParcelableExtra(String key,Class<T> type){return type.cast(extras.get(key));}}
''',
'android/content/IntentFilter.java': 'package android.content; public class IntentFilter {public IntentFilter(){}public IntentFilter(String value){}public void addAction(String value){}public void setPriority(int value){}}',
'android/content/BroadcastReceiver.java': 'package android.content; public abstract class BroadcastReceiver {public abstract void onReceive(Context c,Intent i);public boolean isOrderedBroadcast(){return false;}public void abortBroadcast(){}}',
'android/os/UEventObserver.java': 'package android.os;public abstract class UEventObserver{public static class UEvent{}public abstract void onUEvent(UEvent event);public void startObserving(String match){}}',
'android/os/UserHandle.java': 'package android.os;public class UserHandle{public static final UserHandle CURRENT=new UserHandle();}',
'android/app/ActivityManager.java': 'package android.app;public class ActivityManager{public static int getCurrentUser(){return 0;}}',
'android/Manifest.java': 'package android;public class Manifest{public static class permission{public static final String BLUETOOTH_PRIVILEGED="bluetooth";}}',
'android/os/HandlerThread.java': 'package android.os; public class HandlerThread {public HandlerThread(String name){}public void start(){}public Object getLooper(){return null;}}',
'android/os/PowerManager.java': 'package android.os; public class PowerManager {public boolean isInteractive(){return true;}}',
'android/os/ServiceManager.java': 'package android.os; public class ServiceManager {public static Object controller; public static Object getService(String name){return controller;}}',
'android/bluetooth/BluetoothManager.java': 'package android.bluetooth; public class BluetoothManager {public BluetoothAdapter getAdapter(){return null;}}',
'android/util/Log.java': '''package android.util;
public class Log {public static int i(String t,String v){return 0;}public static int d(String t,String v){return 0;} public static int w(String t,String v){return 0;} public static int w(String t,String v,Throwable e){return 0;} public static int e(String t,String v,Throwable e){return 0;} }
''',
'android/view/Display.java': '''package android.view;
public class Display { public static final int DEFAULT_DISPLAY=0, STATE_ON=2, STATE_OFF=1;
 public int state=STATE_ON; public float rate=144;
 public int getState(){return state;} public Mode getMode(){return new Mode(rate);}
 public static class Mode{float rate;Mode(float r){rate=r;}public float getRefreshRate(){return rate;}}
}
''',
'android/hardware/display/DisplayManager.java': '''package android.hardware.display;
import android.view.Display;
public class DisplayManager{public final Display display=new Display();public Display getDisplay(int id){return display;}
 public interface DisplayListener{void onDisplayAdded(int id);void onDisplayRemoved(int id);void onDisplayChanged(int id);}
 public void registerDisplayListener(DisplayListener listener,android.os.Handler handler){}}
''',
'android/bluetooth/BluetoothProfile.java': 'package android.bluetooth; public class BluetoothProfile {public static final int STATE_CONNECTED=2,STATE_DISCONNECTED=0;}',
'android/bluetooth/BluetoothStatusCodes.java': 'package android.bluetooth; public class BluetoothStatusCodes {public static final int SUCCESS=0;}',
'android/bluetooth/BluetoothAdapter.java': '''package android.bluetooth;
public class BluetoothAdapter{public String address="38:C6:BD:5C:98:87";public String getAddress(){return address;}
 public static final String ACTION_STATE_CHANGED="adapter";public boolean isEnabled(){return true;}
 public java.util.Set<BluetoothDevice> getBondedDevices(){return java.util.Set.of();}
 public BluetoothDevice getRemoteDevice(String address){BluetoothDevice device=new BluetoothDevice(new android.os.Handler());device.address=address;return device;}
 public static boolean checkBluetoothAddress(String v){return v!=null && v.matches("[0-9A-F]{2}(:[0-9A-F]{2}){5}");}}
''',
'android/bluetooth/BluetoothGattCallback.java': '''package android.bluetooth;
public class BluetoothGattCallback {
 public void onConnectionStateChange(BluetoothGatt g,int status,int state){}
 public void onServicesDiscovered(BluetoothGatt g,int status){}
 public void onMtuChanged(BluetoothGatt g,int mtu,int status){}
 public void onCharacteristicRead(BluetoothGatt g,BluetoothGattCharacteristic c,byte[] value,int status){}
 public void onDescriptorWrite(BluetoothGatt g,BluetoothGattDescriptor d,int status){}
 public void onDescriptorRead(BluetoothGatt g,BluetoothGattDescriptor d,int status,byte[] value){}
 public void onCharacteristicWrite(BluetoothGatt g,BluetoothGattCharacteristic c,int status){}
 public void onCharacteristicChanged(BluetoothGatt g,BluetoothGattCharacteristic c,byte[] value){}
}
''',
'android/bluetooth/BluetoothGattCharacteristic.java': '''package android.bluetooth;
import java.util.*;
public class BluetoothGattCharacteristic {
 public static final int PROPERTY_WRITE=8, PROPERTY_NOTIFY=16, WRITE_TYPE_DEFAULT=2, WRITE_TYPE_NO_RESPONSE=1;
 private final UUID id;public byte[] value; public final Map<UUID,BluetoothGattDescriptor> descriptors=new LinkedHashMap<>();
 public BluetoothGattCharacteristic(UUID id,byte[] value){this.id=id;this.value=value;}
 public UUID getUuid(){return id;} public int getProperties(){return PROPERTY_WRITE|PROPERTY_NOTIFY;}
 public BluetoothGattDescriptor getDescriptor(UUID id){return descriptors.get(id);}
}
''',
'android/bluetooth/BluetoothGattDescriptor.java': '''package android.bluetooth;
import java.util.*;
public class BluetoothGattDescriptor {
 public static final byte[] ENABLE_NOTIFICATION_VALUE={1,0};private final UUID id;
 private final BluetoothGattCharacteristic characteristic; public final byte[] value;
 public BluetoothGattDescriptor(UUID id,BluetoothGattCharacteristic c,byte[] value){this.id=id;characteristic=c;this.value=value;c.descriptors.put(id,this);}
 public UUID getUuid(){return id;}public BluetoothGattCharacteristic getCharacteristic(){return characteristic;}
}
''',
'android/bluetooth/BluetoothGattService.java': '''package android.bluetooth;
import java.util.*;
public class BluetoothGattService {
 public final Map<UUID,BluetoothGattCharacteristic> chars=new LinkedHashMap<>();public final List<BluetoothGattCharacteristic> all=new ArrayList<>();
 public void add(BluetoothGattCharacteristic c){chars.put(c.getUuid(),c);all.add(c);}
 public BluetoothGattCharacteristic getCharacteristic(UUID id){return chars.get(id);}
 public List<BluetoothGattCharacteristic> getCharacteristics(){return all;}
}
''',
'android/bluetooth/BluetoothDevice.java': '''package android.bluetooth;
import android.content.Context;import android.os.Handler;
public class BluetoothDevice {
 public static final String ACTION_ACL_CONNECTED="connected",ACTION_ACL_DISCONNECTED="disconnected",ACTION_BOND_STATE_CHANGED="bond";
 public static final String ACTION_PAIRING_REQUEST="pair",EXTRA_DEVICE="device",EXTRA_PAIRING_VARIANT="variant",EXTRA_PAIRING_CONTEXT="context",EXTRA_PAIRING_KEY="key",EXTRA_PAIRING_INITIATOR="initiator";
 public static final int BOND_NONE=10,BOND_BONDING=11,BOND_BONDED=12,ERROR=-1,PAIRING_VARIANT_CONSENT=3,PAIRING_VARIANT_PASSKEY_CONFIRMATION=2,EXTRA_PAIRING_INITIATOR_FOREGROUND=1;
 public int getBondState(){return BOND_BONDED;}public boolean createBond(int transport){return true;}
 public int connect(){return 0;}public boolean setPairingConfirmation(boolean confirmed){return true;}
 public boolean isConnected(){return true;}public int connections;public String address="28:CE:15:31:70:0E";
 public static final int TRANSPORT_LE=2; public String name="Xiaomi Focus Pen Pro";
 public byte[] pnp={1,34,0,(byte)0x81,0x50,1,0};public BluetoothGatt gatt;public final Handler handler;
 public BluetoothDevice(Handler h){handler=h;}
 public String getAddress(){return address;}public String getName(){return name;}
 public BluetoothGatt connectGatt(Context c,boolean auto,BluetoothGattCallback cb,int transport){connections++;gatt=new BluetoothGatt(handler,cb,pnp);BluetoothGatt connection=gatt;handler.postDelayed(()->cb.onConnectionStateChange(connection,0,2),10);return gatt;}
}
''',
'android/bluetooth/BluetoothGatt.java': '''package android.bluetooth;
import android.os.Handler;import java.util.*;
public class BluetoothGatt {
 public final Handler handler;public final BluetoothGattCallback callback;
 public final Map<UUID,BluetoothGattService> services=new HashMap<>();
 public final List<byte[]> commands=new ArrayList<>();public final List<byte[]> subscriptions=new ArrayList<>();
 public final List<String> trace=new ArrayList<>(); public final BluetoothGattCharacteristic command,reply,pressure,buttons;
 public int assignments,pressureStatus,disconnects,closes,pressureAckDelay=10,screenAckDelay=10;public boolean omitWriteCallback,omitReply;
 public int activeReply=1,activeBeforeReply=-1,activeAfterReply=-1;
 public int commandAckDelay=10;
 public boolean failDisconnect,failClose;
 public static UUID sig(String id){return UUID.fromString("0000"+id+"-0000-1000-8000-00805f9b34fb");}
 public BluetoothGatt(Handler h,BluetoothGattCallback cb,byte[] pnp){handler=h;callback=cb;
  BluetoothGattService info=new BluetoothGattService();info.add(new BluetoothGattCharacteristic(sig("2a50"),pnp));services.put(sig("180a"),info);
  BluetoothGattService mipp=new BluetoothGattService();command=new BluetoothGattCharacteristic(UUID.fromString("0000fe11-aa6c-462a-964a-7f2ed5b3e512"),new byte[0]);reply=new BluetoothGattCharacteristic(UUID.fromString("0000fe12-aa6c-462a-964a-7f2ed5b3e512"),new byte[0]);
  new BluetoothGattDescriptor(sig("2902"),reply,new byte[]{0,0});mipp.add(command);mipp.add(reply);services.put(UUID.fromString("0000fe10-aa6c-462a-964a-7f2ed5b3e512"),mipp);
  BluetoothGattService hid=new BluetoothGattService();pressure=new BluetoothGattCharacteristic(sig("2a4d"),new byte[14]);
  new BluetoothGattDescriptor(sig("2908"),pressure,new byte[]{5,1});new BluetoothGattDescriptor(sig("2902"),pressure,new byte[]{0,0});hid.add(pressure);services.put(sig("1812"),hid);
  buttons=new BluetoothGattCharacteristic(sig("2a4d"),new byte[1]);new BluetoothGattDescriptor(sig("2908"),buttons,new byte[]{2,1});new BluetoothGattDescriptor(sig("2902"),buttons,new byte[]{0,0});hid.add(buttons);
 }
 public BluetoothGattService getService(UUID id){return services.get(id);}
 public boolean discoverServices(){handler.postDelayed(()->callback.onServicesDiscovered(this,0),10);return true;}
 public boolean requestMtu(int mtu){handler.postDelayed(()->callback.onMtuChanged(this,mtu,0),10);return true;}
 public boolean readCharacteristic(BluetoothGattCharacteristic c){handler.postDelayed(()->callback.onCharacteristicRead(this,c,c.value,0),10);return true;}
 public boolean setCharacteristicNotification(BluetoothGattCharacteristic c,boolean on){return true;}
 public int writeDescriptor(BluetoothGattDescriptor d,byte[] value){subscriptions.add(value.clone());trace.add(d.getCharacteristic()==pressure?"pressure-ccc":d.getCharacteristic()==buttons?"button-ccc":"reply-ccc");int status=d.getCharacteristic()==pressure?pressureStatus:0;handler.postDelayed(()->callback.onDescriptorWrite(this,d,status),d.getCharacteristic()==pressure?pressureAckDelay:10);return 0;}
 public boolean readDescriptor(BluetoothGattDescriptor d){handler.postDelayed(()->callback.onDescriptorRead(this,d,0,d.value),10);return true;}
 public int writeCharacteristic(BluetoothGattCharacteristic c,byte[] value,int type){
  commands.add(value.clone());trace.add(String.format("command-%02x",value[0]&255));int op=value[0]&255;
  int length=op<4?new int[]{1,2,2,3}[op]:op==4||op==0x52?1:0;
  byte[] response=new byte[length+2];response[0]=(byte)(op|128);response[1]=(byte)length;
  if(op==4)response[2]=(byte)assignments++;if(op==0x52)response[2]=(byte)activeReply;
  if(op==0x52 && activeBeforeReply>=0){byte state=(byte)activeBeforeReply;handler.postDelayed(()->callback.onCharacteristicChanged(this,reply,new byte[]{0x53,1,state}),2);}
  if(op==0x52 && activeAfterReply>=0){byte state=(byte)activeAfterReply;handler.postDelayed(()->callback.onCharacteristicChanged(this,reply,new byte[]{0x53,1,state}),8);}
  // Deliberately deliver the notification before write completion.
  if(!omitReply)handler.postDelayed(()->callback.onCharacteristicChanged(this,reply,response),op==0x61?screenAckDelay-5:5);
  if(!omitWriteCallback)handler.postDelayed(()->callback.onCharacteristicWrite(this,c,0),op==0x61?screenAckDelay:commandAckDelay);
  return 0;
 }
 public void disconnect(){disconnects++;if(failDisconnect)throw new SecurityException("Bluetooth disconnect unavailable");}
 public void close(){closes++;if(failClose)throw new IllegalStateException("Bluetooth close unavailable");}
}
''',
'vendor/lineage/sheng/stylus/IPenController.java': '''package vendor.lineage.sheng.stylus;
import android.os.Binder;
public interface IPenController{int APPLIED=0,DEFERRED=1,BUSY=2,INVALID=3,ERROR=4;
 class Stub {public static IPenController asInterface(Object value){return (IPenController)value;}}
 int acquire(Binder owner,int product,String address)throws Exception;int setMode(Binder owner,int mode,int value)throws Exception;
 int release(Binder owner)throws Exception;long getForwardedCount(Binder owner)throws Exception;}
''',
'org/lineageos/sheng/stylus/DisplayRateLease.java': '''package org.lineageos.sheng.stylus;
import android.content.Context;
public class DisplayRateLease{static android.view.Display display;private boolean held;
 public DisplayRateLease(Context c){}public void acquire(float rate){held=true;display.rate=rate;}public void close(){if(held){display.rate=144;held=false;}}}
''',
'org/lineageos/sheng/stylus/PenInputLease.java': '''package org.lineageos.sheng.stylus;
public class PenInputLease{int guards,proGuards,restores;long readyAt;boolean restoreReady=true;
 boolean pointerEnabled;void setPointerEnabled(boolean enabled){pointerEnabled=enabled;}
 PenInputLease(){}PenInputLease(android.content.Context context){}
 boolean guard(PenModel model,int product,String address){guards++;if(model==PenModel.PRO)proGuards++;return android.os.SystemClock.now>=readyAt;}
 boolean restore(){restores++;return restoreReady;}}
''',
'org/lineageos/sheng/stylus/PenPanelObserver.java': '''package org.lineageos.sheng.stylus;
import android.os.Handler;import java.util.function.IntConsumer;
public class PenPanelObserver{static PenPanelObserver latest;private final IntConsumer callback;boolean active,failClose;
 PenPanelObserver(Handler h,IntConsumer cb){callback=cb;latest=this;}void start(){active=true;}void close(){active=false;if(failClose)throw new IllegalStateException("observer close unavailable");}void event(int value){if(active)callback.accept(value);}}
''',
'org/lineageos/sheng/stylus/PenShortcutController.java': '''package org.lineageos.sheng.stylus;
class PenShortcutController {static PenShortcutController latest;boolean available,closed;PenModel model;int reports;
 java.util.function.Consumer<Boolean> pointer;
 PenShortcutController(android.content.Context context,android.os.Handler actor,java.util.function.IntConsumer feedback,java.util.function.Consumer<Boolean> pointerMode,java.util.function.Consumer<Boolean> pointerButton){latest=this;pointer=pointerMode;}
 void setModel(PenModel value){model=value;}void setPointerIdentity(int product,String address){}void setAvailable(boolean value){available=value;}
 void report(byte[] value){if(available&&!closed)reports++;}void close(){closed=true;available=false;}}
''',
'org/lineageos/sheng/pen/controls/PenControlsSettings.java': '''package org.lineageos.sheng.pen.controls;
public class PenControlsSettings{public static int vibration(android.content.Context context,int user){return 3;}
 public static int sensitivity(android.content.Context context,int user){return 2;}}
''',
'org/lineageos/sheng/stylus/PenActorTest.java': '''package org.lineageos.sheng.stylus;
import android.bluetooth.*;import android.os.*;import android.content.Context;import android.hardware.display.DisplayManager;import android.view.Display;
import vendor.lineage.sheng.stylus.IPenController;import java.util.*;
public class PenActorTest {
 static int checks; static void check(boolean value,String reason){checks++;if(!value)throw new AssertionError(reason);}
 static class Native implements IPenController {
  int acquires,releases,releaseAttempts,ready,deferActive,activeState=-1;boolean owned,on=true,lost,suspended=true;
  final List<String> calls=new ArrayList<>();
  public int acquire(Binder token,int product,String address){if(!on)return DEFERRED;if(owned)return BUSY;owned=true;acquires++;calls.add("acquire");return APPLIED;}
  public int setMode(Binder token,int mode,int value){calls.add(mode+":"+value);if(!on)throw new AssertionError("Off controller write");if(mode==29&&deferActive-->0)return DEFERRED;if(mode==29)activeState=value;if(mode==37){ready=value;if(value==1)suspended=false;}return APPLIED;}
  public int release(Binder token){releaseAttempts++;if(!owned)return BUSY;owned=false;releases++;calls.add("release");return on?APPLIED:DEFERRED;}
  public long getForwardedCount(Binder token){return lost||!owned?-1:ready==1&&suspended?-2:0;}
 }
 static class Run {
  Handler h=new Handler();DisplayManager displays=new DisplayManager();BluetoothDevice pen=new BluetoothDevice(h);BluetoothAdapter adapter=new BluetoothAdapter();
  Native nativeControl=new Native();PenInputLease inputs=new PenInputLease();PenGattSession session;int finished,dock=1;
  Run(){SystemClock.now=0;DisplayRateLease.display=displays.display;}
  void start(){session=new PenGattSession(new Context(),h,pen,adapter,nativeControl,inputs,displays,()->finished++);session.observe(true,dock);session.start();}
  void run(long duration){for(long t=0;t<duration;t+=100){session.observe(displays.display.state==Display.STATE_ON,dock);h.advance(100);}}
  long count(int opcode){return pen.gatt.commands.stream().filter(b->(b[0]&255)==opcode).count();}
  void off(){nativeControl.on=false;nativeControl.suspended=true;displays.display.state=Display.STATE_OFF;session.observe(false,dock);}
  void on(){nativeControl.on=true;displays.display.state=Display.STATE_ON;session.observe(true,dock);}
 }
 static void dockWake(){Run r=new Run();r.start();r.run(4000);
  check(r.nativeControl.acquires==1&&r.nativeControl.ready==1,"initial native owner/ready");
  check(r.pen.gatt.assignments==2,"two IDs allocated exactly once");
  check(r.pen.gatt.trace.contains("pressure-ccc"),"real actor subscribes report 5");
  check(r.pen.gatt.trace.lastIndexOf("command-30")<r.pen.gatt.trace.indexOf("pressure-ccc"),"pressure subscription follows ready timing");
  r.dock=0;r.run(3000);check(r.nativeControl.ready==0&&r.displays.display.rate==144,"dock clears ready and releases display vote");
  check(r.nativeControl.acquires==1&&r.nativeControl.releases==0,"dock retains one connection owner");
  r.dock=1;r.run(3000);check(r.nativeControl.ready==1&&r.displays.display.rate==120,"undock restores writing request");
  check(r.pen.gatt.assignments==2&&r.nativeControl.acquires==1,"undock reuses existing IDs and connection");
  int commands=r.pen.gatt.commands.size(),modes=r.nativeControl.calls.size();r.off();r.run(3000);
  check(r.nativeControl.calls.size()==modes,"no Off native modes");check(r.pen.gatt.commands.subList(commands,r.pen.gatt.commands.size()).stream().allMatch(b->b.length==3 && b[0]==0x61 && b[2]==0),"Off sends only Pro screen status, no reinitialization");
  r.on();r.run(3000);check(r.nativeControl.ready==1&&r.displays.display.rate==120,"wake resumes writing");
  check(r.pen.gatt.assignments==2&&r.nativeControl.acquires==1,"wake does not allocate IDs or another connection");
  check(r.count(0x52)==3,"Pro undock and wake each read the actual active state without new notifications");
  r.session.onConnectionStateChange(r.pen.gatt,0,0);r.h.advance(100);
  check(r.finished==1&&r.nativeControl.releases==1&&r.inputs.restores==1,"disconnect cleans owner and guarded input once");
  check(r.displays.display.rate==144,"disconnect removes display request");
  r.session.close("duplicate");check(r.nativeControl.releaseAttempts==1&&r.finished==1,"duplicate close does not decrement");
  check(r.pen.gatt.subscriptions.stream().allMatch(v->v[0]==1),"shared HID CCCD never disabled by cleanup");
 }
 static void failures(){Run r=new Run();r.start();r.pen.gatt.pressureStatus=3;r.run(4000);
  check(r.finished==1&&r.nativeControl.releases==1&&r.inputs.restores==1,"pressure CCCD rejection restores acquired lease");
  check(r.displays.display.rate==144,"CCCD failure removes display vote");
  r=new Run();r.pen.pnp[0]=2;r.start();r.run(3000);
  check(r.finished==1&&r.nativeControl.acquires==0&&r.inputs.proGuards==0,"wrong vendor namespace cannot acquire hardware/input");
  r=new Run();r.start();r.pen.gatt.omitWriteCallback=true;r.run(18000);
  check(r.finished==1&&r.nativeControl.acquires==0,"reply alone does not complete write transaction");
  r=new Run();r.start();r.run(4000);r.nativeControl.lost=true;r.nativeControl.owned=false;r.run(1000);
  check(r.finished==1&&r.nativeControl.releases==0&&r.nativeControl.releaseAttempts==1,"lost native ownership cannot fabricate driver disconnect");
 }
 static void ordinary(){Run r=new Run();r.pen.name="Xiaomi Focus Pen";r.pen.pnp=new byte[]{1,34,0,(byte)0x80,0x4d,1,0};r.start();r.run(4000);
  check(r.nativeControl.ready==1&&r.nativeControl.acquires==1,"ordinary connection initialization branch");
  check(r.count(0x52)==0&&r.count(0x61)==0,"ordinary does not receive Pro active/screen commands");
  check(r.pen.gatt.trace.contains("pressure-ccc")&&r.inputs.guards>0&&r.inputs.proGuards==0,"ordinary subscribes measured report 5 and guards its own companion input");
 }
 static void nativePauseRecovery(){for(boolean ordinary:new boolean[]{true,false}){
  Run r=new Run();if(ordinary){r.pen.name="Xiaomi Focus Pen";r.pen.pnp=new byte[]{1,34,0,(byte)0x80,0x4d,1,0};}r.start();r.run(4000);
  PenShortcutController shortcuts=PenShortcutController.latest;
  check(r.pen.gatt.trace.contains("button-ccc")&&shortcuts.available,"report 2 subscribed and enabled after ready");
  check(r.pen.gatt.trace.indexOf("pressure-ccc")<r.pen.gatt.trace.indexOf("button-ccc"),"buttons follow pressure setup");
  shortcuts.pointer.accept(true);r.run(100);
  check(r.inputs.pointerEnabled,"mouse selection reaches actor input policy");
  check(r.count(0x50)==(ordinary?0:2),"Pro synchronizes pointer off before enabling mouse; ordinary sends no mouse commands");
  shortcuts.pointer.accept(true);r.run(100);
  check(r.inputs.pointerEnabled&&r.count(0x50)==(ordinary?0:3),"active Pro mode can be resynchronized after firmware slide exit");
  shortcuts.pointer.accept(false);r.run(100);
  check(!r.inputs.pointerEnabled&&r.count(0x50)==(ordinary?0:4),"mouse deselection restores input policy and Pro mode");
  int reports=shortcuts.reports;
  r.session.onCharacteristicChanged(r.pen.gatt,r.pen.gatt.buttons,new byte[]{0x6e});r.h.advance(0);
  check(shortcuts.reports==reports+1,"real report 2 reaches shortcut boundary");
  int start=r.nativeControl.calls.size();r.nativeControl.suspended=true;r.session.observe(true,1);
  check(!shortcuts.available,"native-only pause disables shortcuts during timing recovery");
  r.run(3000);
  check(!r.nativeControl.suspended&&r.nativeControl.ready==1&&r.finished==0,"native-only pause recovers without screen transition");
  List<String> modes=r.nativeControl.calls.subList(start,r.nativeControl.calls.size());
  check(modes.indexOf("37:0")>=0&&modes.indexOf("37:0")<modes.indexOf("22:1")&&modes.indexOf("22:1")<modes.indexOf("22:259")&&modes.indexOf("22:259")<modes.indexOf("37:1"),"resume restores both original timing IDs before ready");
  check(r.nativeControl.acquires==1&&r.pen.gatt.assignments==2,"native-only pause retains owner and allocated IDs");
  check(shortcuts.available,"shortcuts return after timing recovery");
  r.dock=0;r.run(2000);check(!shortcuts.available,"docked shortcuts disabled");
  r.dock=1;r.run(3000);check(shortcuts.available,"undocked shortcuts restored");
  r.off();int count=r.nativeControl.calls.size();r.run(2000);
  check(!shortcuts.available&&r.nativeControl.calls.size()==count,"Off disables buttons without controller writes");
  r.on();r.run(3000);check(shortcuts.available,"wake restores buttons");
  r.session.close("test complete");check(shortcuts.closed&&!shortcuts.available,"disconnect closes shortcuts");
 }}
 static void deferredActive(){Run r=new Run();r.start();r.run(4000);r.nativeControl.deferActive=1;
  r.session.onCharacteristicChanged(r.pen.gatt,r.pen.gatt.reply,new byte[]{0x53,1,1});r.h.advance(0);
  int n=r.pen.gatt.commands.size();PenPanelObserver.latest.event((0x31<<16)|1);r.h.advance(100);
  check(r.pen.gatt.commands.size()==n,"frequency waits behind deferred native mode");
  r.run(1200);check(r.count(0x31)>=3,"queued frequency sent after deferred mode completes");
  check(r.finished==0,"no asynchronous controller/GATT overlap");
 }
 static void delayedGuardOff(){Run r=new Run();r.inputs.readyAt=3000;r.start();r.run(1500);r.off();
  int count=r.pen.gatt.commands.size();r.run(4000);
  check(r.pen.gatt.commands.size()==count,"delayed input guard cannot start MIPP commands during Off");
  r.on();r.run(4000);check(r.nativeControl.ready==1&&r.pen.gatt.assignments==2,"delayed guard resumes after wake");
 }
 static void screenOffWake(){Run r=new Run();r.start();r.run(4000);
  long before=r.pen.gatt.commands.stream().filter(b->b.length==3 && b[0]==0x61 && b[2]==0).count();
  int modes=r.nativeControl.calls.size();r.off();r.run(1000);
  long after=r.pen.gatt.commands.stream().filter(b->b.length==3 && b[0]==0x61 && b[2]==0).count();
  check(after==before+1,"initialized Pro must receive one explicit screen-Off GATT state");
  check(r.nativeControl.calls.size()==modes,"screen-Off GATT status never writes the Off controller");
  r.run(2000);check(r.pen.gatt.commands.stream().filter(b->b.length==3 && b[0]==0x61 && b[2]==0).count()==after,"Off polling does not flood the pen");
  r.on();r.run(4000);check(r.nativeControl.ready==1 && r.finished==0,"wake resumes after Off state acknowledgement");
  check(r.pen.gatt.assignments==2 && r.nativeControl.acquires==1,"screen transition keeps the original IDs and connection");
 }
 static void setupOffWake(){Run r=new Run();r.start();r.pen.gatt.pressureAckDelay=2500;r.run(2000);
  check(r.nativeControl.ready==1 && r.pen.gatt.trace.contains("pressure-ccc"),"fixture reaches native ready before pressure ACK");
  r.off();r.run(3000);
  check(r.nativeControl.suspended,"native Off requires a new ready command");
  r.on();r.run(5000);
  check(!r.nativeControl.suspended && r.nativeControl.ready==1 && r.finished==0,"Off during setup rearms the real native gate after wake");
  check(r.pen.gatt.assignments==2 && r.nativeControl.acquires==1,"setup recovery reuses both IDs and one connection");
 }
 static void initialScreenAckOff(){Run r=new Run();r.start();r.pen.gatt.screenAckDelay=1500;r.run(2000);
  check(r.count(0x61)==1 && r.nativeControl.ready==0,"fixture waits for initial screen-On ACK before ready");
  r.off();r.run(2500);check(r.nativeControl.ready==0,"initial screen ACK during Off does not enable the controller");
  r.on();r.run(7000);
  check(r.nativeControl.ready==1 && !r.nativeControl.suspended && r.finished==0,"initial continuation survives the separate Off and On ACKs");
  check(r.pen.gatt.assignments==2,"screen-status transactions never reallocate initial IDs");
 }
 static void dockedScreenWake(){Run r=new Run();r.start();r.run(4000);r.dock=0;r.run(3000);
  check(r.displays.display.rate==144 && r.nativeControl.ready==0,"docked fixture releases the display vote");
  r.off();r.run(2000);long ons=r.count(0x61);r.on();r.run(4000);
  check(r.count(0x61)==ons+1,"docked wake still reports actual screen-On to Pro");
  check(r.displays.display.rate==144 && r.nativeControl.ready==0 && r.finished==0,"docked screen report finishes without retaining a 120 Hz vote or enabling writing");
 }
 static void statusAckReordered(){Run r=new Run();r.start();r.run(4000);r.pen.gatt.screenAckDelay=800;
  int modes=r.nativeControl.calls.size();r.off();r.run(100);r.on();r.run(1300);
  check(r.nativeControl.calls.size()==modes,"wake controller continuation waits behind the screen-status ACK");
  r.off();r.run(2000);
  check(r.nativeControl.calls.size()==modes,"late screen-On ACK during a second Off never writes the controller");
  long offs=r.pen.gatt.commands.stream().filter(b->b.length==3 && b[0]==0x61 && b[2]==0).count();
  check(offs==2,"a second Off supersedes the pending screen-On status exactly once");
  r.on();r.run(6000);check(r.nativeControl.ready==1 && !r.nativeControl.suspended && r.finished==0,"latest On restores the original continuation after rapid screen changes");
  check(r.pen.gatt.assignments==2 && r.nativeControl.acquires==1,"rapid screen changes retain the owned session");
 }
 static void ordinaryWake(){Run r=new Run();r.pen.name="Xiaomi Focus Pen";r.pen.pnp=new byte[]{1,34,0,(byte)0x80,0x4d,1,0};r.start();r.run(4000);
  r.off();r.run(2000);r.on();r.run(4000);
  check(r.count(0x61)==0 && r.count(0x52)==0,"ordinary Off/On never acquires Pro screen or active commands");
  check(r.nativeControl.ready==1 && !r.nativeControl.suspended && r.finished==0,"ordinary wake restores its own native ready gate");
  check(r.pen.gatt.assignments==2 && r.nativeControl.acquires==1,"ordinary wake reuses its original IDs and connection");
 }
 static void screenWriteTimeout(){Run r=new Run();r.start();r.run(4000);r.pen.gatt.omitWriteCallback=true;
  r.off();r.run(100);r.on();r.run(18000);
  check(r.finished==1 && r.nativeControl.releases==1 && r.inputs.restores==1,"screen reply without write ACK times out and releases one owner");
  check(r.displays.display.rate==144,"screen-state transaction failure releases its display token");
 }
 static void cleanupFailures(){Run r=new Run();r.start();r.run(4000);
  PenPanelObserver.latest.failClose=true;r.pen.gatt.failDisconnect=true;r.pen.gatt.failClose=true;
  boolean escaped=false;try{r.session.close("Bluetooth unavailable");}catch(RuntimeException error){escaped=true;}
  check(!escaped,"one resource cleanup failure cannot escape and strand the session");
  check(r.pen.gatt.disconnects==1 && r.pen.gatt.closes==1,"GATT disconnect and close are independently attempted after observer failure");
  check(r.nativeControl.releases==1 && r.inputs.restores==1 && r.finished==1,"cleanup failures still release native ownership, restore input and finish the session");
  check(r.displays.display.rate==144,"cleanup failures still release the display request");
  r.session.close("duplicate");r.run(20000);
  check(r.nativeControl.releaseAttempts==1 && r.finished==1,"duplicate close and late callbacks cannot repeat ownership release");
 }
 static void activeStateOrder(){
  for(int state=0;state<=1;state++){
   Run r=new Run();r.start();r.pen.gatt.activeReply=state;r.pen.gatt.activeBeforeReply=1-state;r.run(4000);
   check(r.finished==0 && r.nativeControl.activeState==state,"current active query supersedes an older notification, state="+state);
   check(r.nativeControl.calls.stream().filter(v->v.startsWith("29:")).count()==1,"older notification cannot be replayed after ready");
   r=new Run();r.start();r.pen.gatt.activeReply=1-state;r.pen.gatt.activeAfterReply=state;r.run(4000);
   check(r.finished==0 && r.nativeControl.activeState==state,"notification after query reply but before write ACK supplies the latest state="+state);
   check(!r.nativeControl.calls.contains("29:"+(1-state)),"a delayed write ACK cannot apply the superseded query state");
  }
  Run r=new Run();r.start();r.run(4000);r.off();
  r.session.onCharacteristicChanged(r.pen.gatt,r.pen.gatt.reply,new byte[]{0x53,1,0});r.run(1000);r.on();r.run(4000);
  check(r.finished==0 && r.nativeControl.activeState==1 && r.nativeControl.ready==1,"wake query supersedes the queued pre-wake sleep state");
  check(r.pen.gatt.assignments==2 && r.nativeControl.acquires==1,"active-state reconciliation retains the original IDs and connection");
  r=new Run();r.start();r.pen.gatt.activeReply=2;r.pen.gatt.activeAfterReply=1;r.run(4000);
  check(r.finished==1 && r.nativeControl.releases==1,"a newer valid notification cannot conceal an invalid query response");
 }
 static void unavailableDock(){Run r=new Run();r.start();r.run(4000);r.dock=-1;r.run(100);
  check(r.finished==1 && r.nativeControl.releases==1 && !r.nativeControl.owned,"unknown dock while On releases the active native pressure lease");
  check(r.inputs.restores==1 && r.displays.display.rate==144,"unknown dock restores owned input and the display vote");
  r=new Run();r.start();r.run(4000);r.off();r.dock=-1;r.run(2000);
  check(r.finished==0 && r.nativeControl.releases==0,"unavailable dock during Off does not disturb the suspended connection");
  r.dock=1;r.on();r.run(4000);
  check(r.finished==0 && r.nativeControl.ready==1 && r.pen.gatt.assignments==2,"known dock on wake resumes the same connection");
 }
 static void displayConstraintLoss(){
  for(float rate:new float[]{30,144}){Run r=new Run();r.start();r.run(4000);r.displays.display.rate=rate;r.run(100);
   check(r.finished==1 && !r.nativeControl.owned,"native forwarding is released when actual display rate leaves the supported range: "+rate);
   check(r.inputs.restores==1 && r.nativeControl.releaseAttempts==1,"unsupported display cleanup restores input and releases the owner once");}
  Run r=new Run();r.start();r.pen.gatt.pressureAckDelay=2500;r.run(2000);
  check(r.nativeControl.ready==1,"display-loss fixture reaches native ready before pressure CCCD ACK");
  r.displays.display.rate=144;r.run(3000);
  check(r.finished==1 && r.nativeControl.releases==1 && r.inputs.restores==1,"native-ready setup also releases on unsupported display rate before late CCCD ACK");
  r=new Run();r.start();r.run(4000);r.displays.display.rate=60;r.run(2000);
  check(r.finished==0 && r.nativeControl.ready==1 && r.nativeControl.acquires==1,"supported 60 Hz transition retains the existing pen session");
 }
 static void transitionStress(){
  for(int seed=0;seed<12;seed++){
   Run r=new Run();r.start();r.run(4000);Random events=new Random(0x508100L+seed);
   for(int tick=0;tick<500;tick++){
    r.pen.gatt.screenAckDelay=50+events.nextInt(950);r.pen.gatt.commandAckDelay=10+events.nextInt(290);
    int event=events.nextInt(100);
    if(event<8){if(r.nativeControl.on)r.off();else r.on();}
    else if(event<18)r.dock=1-r.dock;
    else if(event<28)r.session.onCharacteristicChanged(r.pen.gatt,r.pen.gatt.reply,new byte[]{0x53,1,(byte)events.nextInt(2)});
    r.run(100);
    if(r.finished!=0)throw new AssertionError("legitimate screen/dock/state transition closed the session, seed="+seed+" tick="+tick);
   }
   r.dock=1;r.on();r.run(15000);
   check(r.finished==0 && r.nativeControl.ready==1 && !r.nativeControl.suspended,"settled writing resumes after interleaved delayed ACKs, seed="+seed);
   check(r.pen.gatt.assignments==2 && r.nativeControl.acquires==1 && r.nativeControl.releases==0,"rapid transitions keep two IDs and one owner, seed="+seed);
   r.session.close("stress complete");
   check(r.finished==1 && r.nativeControl.releases==1 && r.inputs.restores==1,"stress cleanup releases one native/input lease, seed="+seed);
  }
 }
public static void main(String[] args)throws Exception{dockWake();failures();ordinary();nativePauseRecovery();deferredActive();delayedGuardOff();if(args.length>0){screenOffWake();setupOffWake();initialScreenAckOff();dockedScreenWake();statusAckReordered();ordinaryWake();screenWriteTimeout();}cleanupFailures();activeStateOrder();unavailableDock();displayConstraintLoss();transitionStress();PenApplicationTest.run();System.out.println("PASS actor_checks="+checks+" hardware_tested=false input_journal_tested=false");}
}
''',
'org/lineageos/sheng/stylus/PenApplicationTest.java': '''package org.lineageos.sheng.stylus;
import android.bluetooth.*;import android.os.*;import android.hardware.display.DisplayManager;
import java.lang.reflect.Field;import java.util.*;
public class PenApplicationTest {
 static class Run {
  ShengStylusApplication app=new ShengStylusApplication();Handler actor=new Handler();
  DisplayManager displays=new DisplayManager();BluetoothAdapter adapter=new BluetoothAdapter();
  BluetoothDevice pen=new BluetoothDevice(actor);PenInputLease inputs=new PenInputLease();
  PenActorTest.Native nativeControl=new PenActorTest.Native();
  Run()throws Exception{SystemClock.now=0;DisplayRateLease.display=displays.display;ServiceManager.controller=nativeControl;
   for(Object[] entry:new Object[][]{{"actor",actor},{"bluetooth",adapter},{"displays",displays},{"inputs",inputs}}){
    Field field=ShengStylusApplication.class.getDeclaredField((String)entry[0]);field.setAccessible(true);field.set(app,entry[1]);}}
  void poll(List<BluetoothDevice> devices,long duration)throws Exception{
   for(long elapsed=0;elapsed<duration;elapsed+=100){app.reconcileConnection(devices,true,1);actor.advance(100);}}
  void connected(long duration)throws Exception{poll(List.of(pen),duration);}
  void disconnected()throws Exception{poll(List.of(),100);}
  void failGatt(){pen.gatt.callback.onConnectionStateChange(pen.gatt,133,0);actor.advance(0);}
 }
 static void check(boolean value,String reason){PenActorTest.check(value,reason);}
 static void physicalReconnect()throws Exception{
  Run r=new Run();r.connected(4000);
  check(r.nativeControl.acquires==1,"application establishes the first pen session");
  for(int cycle=1;cycle<=4;cycle++){
   r.disconnected();check(r.nativeControl.releases==cycle,"physical disconnect releases one owner");
   r.connected(65000);
   check(r.nativeControl.acquires==cycle+1,"same pen reconnects with unchanged screen and dock after disconnect "+cycle);
  }
  r.disconnected();r.connected(4000);
  check(r.nativeControl.acquires==6,"physical reconnect also starts without the old failure delay");
 }
 static void failedSameLink()throws Exception{
  Run r=new Run();r.connected(4000);r.failGatt();r.connected(5000);
  check(r.pen.connections==1,"same-link failure retains retry delay across repeated polls");
  r.connected(6000);check(r.pen.connections==2,"same-link failure retries after the delay");
  r.failGatt();r.connected(21000);check(r.pen.connections==3,"second same-link failure permits the final retry");
  r.failGatt();r.connected(90000);check(r.pen.connections==3,"three same-link failures remain capped despite polling");
  r.disconnected();r.connected(4000);
  check(r.pen.connections==4,"observed physical reconnect clears the exhausted retry budget");
 }
 static void ambiguousAndReplacement()throws Exception{
  Run r=new Run();r.connected(4000);BluetoothDevice other=new BluetoothDevice(r.actor);other.address="28:CE:15:31:70:0F";
  r.poll(List.of(r.pen,other),4000);
  check(r.nativeControl.releases==1 && other.connections==0,"ambiguous connected pens release ownership without selecting a peer");
  r.connected(4000);check(r.nativeControl.acquires==2,"returning to one observed peer restores eligibility");
  r.poll(List.of(other),4000);
  check(other.connections==1 && r.nativeControl.acquires==3,"a different observed peer receives a separate retry budget");
 }
 static void restoreBeforeAcquire()throws Exception{
  Run r=new Run();r.inputs.restoreReady=false;r.connected(4000);
  check(r.pen.connections==0 && r.nativeControl.acquires==0,"pending input restoration blocks a new GATT/native session");
  r.inputs.restoreReady=true;r.connected(4000);check(r.nativeControl.acquires==1,"completed input restoration permits a session");
  r.inputs.restoreReady=false;r.disconnected();r.connected(4000);
  check(r.pen.connections==1,"reconnected peer still waits for its prior input restoration");
  r.inputs.restoreReady=true;r.connected(4000);
  check(r.nativeControl.acquires==2,"disconnect observation survives pending input restoration");
 }
 static void run()throws Exception{physicalReconnect();failedSameLink();ambiguousAndReplacement();restoreBeforeAcquire();}
}
'''
}
sources = []
for relative, body in fixtures.items():
    path = WORK/'fixtures'/relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding='utf-8')
    sources.append(path)
actual = [SOURCE/'app/org/lineageos/sheng/stylus/PenGattSession.java',
          SOURCE/'app/org/lineageos/sheng/stylus/ShengStylusApplication.java',
          SOURCE/'src/org/lineageos/sheng/stylus/PenModel.java',
          SOURCE/'src/org/lineageos/sheng/stylus/MippProfile.java',
          SOURCE/'src/org/lineageos/sheng/stylus/PenWakeGate.java',
          SOURCE/'src/org/lineageos/sheng/stylus/PenFeatureCommands.java',
          SOURCE.parent/'pen/common/org/lineageos/sheng/pen/charge/ChargeStatus.java',
          SOURCE.parent/'pen/common/org/lineageos/sheng/pen/charge/PenDockPeer.java']
jdk = ROM/'prebuilts/jdk/jdk21/linux-x86/bin'
compile_result = subprocess.run([jdk/'javac', '-encoding', 'UTF-8', '-d', WORK/'classes', *sources, *actual],
                                text=True, capture_output=True)
receipt = dict(date_utc=datetime.now(timezone.utc).isoformat(), kind='actual-actor-deterministic-host-harness',
               power_lifecycle_suite=args.power_lifecycle,
               application_reconnect_suite=True,
               cleanup_failure_suite=True,
               active_state_order_suite=True,
               dock_display_loss_suite=True,
               transition_stress_seeds=12,
               transition_stress_ticks_per_seed=500,
               actual_source_sha256={str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in actual},
               compiled=compile_result.returncode==0, compile_stdout=compile_result.stdout,
               compile_stderr=compile_result.stderr, hardware_tested=False,
               android_framework_tested=False, input_journal_tested=False, policy_tested=False)
if compile_result.returncode == 0:
    result = subprocess.run([jdk/'java', '-cp', WORK/'classes', 'org.lineageos.sheng.stylus.PenActorTest',
                             *(['--power-lifecycle'] if args.power_lifecycle else [])],
                            text=True, capture_output=True)
    receipt.update(passed=result.returncode==0, stdout=result.stdout, stderr=result.stderr, exit_code=result.returncode)
else:
    receipt.update(passed=False, exit_code=compile_result.returncode)
(WORK/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
print(str(WORK))
print(json.dumps(receipt, indent=2))
raise SystemExit(0 if receipt['passed'] else 1)
