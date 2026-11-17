shortcut_fixtures = {
    'android/content/Context.java': '''package android.content;
public class Context {
public final java.util.Map<Class<?>,Object> services=new java.util.HashMap<>();
public final android.content.ContentResolver resolver=new android.content.ContentResolver();
public final android.content.pm.PackageManager packages=new android.content.pm.PackageManager();
public android.content.ContentResolver getContentResolver(){return resolver;}
public android.content.pm.PackageManager getPackageManager(){return packages;}
public <T> T getSystemService(Class<T> type){return type.cast(services.get(type));}
public android.content.res.Resources getResources(){return new android.content.res.Resources();}
public void startActivityAsUser(Intent intent,android.os.UserHandle user){}
}''',
    'android/content/ContentResolver.java': '''package android.content;
public class ContentResolver {
public android.database.ContentObserver observer;
public void registerContentObserver(android.net.Uri uri,boolean descendants,android.database.ContentObserver observer,int user){this.observer=observer;}
public void unregisterContentObserver(android.database.ContentObserver observer){this.observer=null;}}
''',
    'android/net/Uri.java': 'package android.net;public class Uri {}',
    'android/database/ContentObserver.java': '''package android.database;
public class ContentObserver {public ContentObserver(android.os.Handler handler){}public void onChange(boolean selfChange){}}''',
    'android/provider/Settings.java': '''package android.provider;
public class Settings {public static class Secure {public static android.net.Uri getUriFor(String key){return new android.net.Uri();}}}''',
    'android/content/ComponentName.java': '''package android.content;
public class ComponentName {private final String name;public ComponentName(String name,String activity){this.name=name;}
public String getPackageName(){return name;}}''',
    'android/content/pm/ApplicationInfo.java': 'package android.content.pm;public class ApplicationInfo {public int uid;}',
    'android/content/pm/PackageManager.java': '''package android.content.pm;
public class PackageManager {public int uid=12345;public boolean missing;
public static class NameNotFoundException extends Exception {}
public ApplicationInfo getApplicationInfoAsUser(String name,int flags,int user) throws NameNotFoundException {
if(missing)throw new NameNotFoundException();ApplicationInfo info=new ApplicationInfo();info.uid=uid;return info;}}''',
    'android/os/RemoteException.java': 'package android.os;public class RemoteException extends Exception {}',
    'android/app/TaskStackListener.java': '''package android.app;
public class TaskStackListener {public void onTaskStackChanged(){}public void onTaskFocusChanged(int task,boolean focused){}}''',
    'android/app/ActivityTaskManager.java': '''package android.app;
public class ActivityTaskManager {
public static final Service service=new Service();public static Service getService(){return service;}
public static class RootTaskInfo {public android.content.ComponentName topActivity;public int userId,displayId;}
public static class Service {public RootTaskInfo focused;public TaskStackListener listener;public boolean fail;
public RootTaskInfo getFocusedRootTaskInfo() throws android.os.RemoteException {if(fail)throw new android.os.RemoteException();return focused;}
public void registerTaskStackListener(TaskStackListener listener) throws android.os.RemoteException {this.listener=listener;}
public void unregisterTaskStackListener(TaskStackListener listener) throws android.os.RemoteException {this.listener=null;}}}
''',
    'android/content/res/Resources.java': '''package android.content.res;
public class Resources {
public android.util.DisplayMetrics getDisplayMetrics(){return new android.util.DisplayMetrics();}
public Configuration getConfiguration(){return new Configuration();}
}''',
    'android/content/res/Configuration.java': '''package android.content.res;
public class Configuration {public android.os.LocaleList getLocales(){return new android.os.LocaleList();}}''',
    'android/os/LocaleList.java': '''package android.os;
public class LocaleList {public java.util.Locale get(int index){return java.util.Locale.ENGLISH;}}''',
    'android/util/Log.java': '''package android.util;
public class Log {public static final java.util.List<String> messages=new java.util.ArrayList<>();
public static int i(String tag,String message){messages.add(message);return 0;}
public static int w(String tag,String message){messages.add(message);return 0;}
public static int w(String tag,String message,Throwable error){messages.add(message);return 0;}}
''',
    'android/os/Looper.java': '''package android.os;
public class Looper {public static final Looper MAIN=new Looper();public static Looper getMainLooper(){return MAIN;}}''',
    'android/os/SystemClock.java': '''package android.os;
public class SystemClock {public static long now=1000;public static long uptimeMillis(){return now;}}''',
    'android/os/Handler.java': '''package android.os;
public class Handler {
private static class Task {Handler owner;Runnable action;long at,order;
Task(Handler owner,Runnable action,long at,long order){this.owner=owner;this.action=action;this.at=at;this.order=order;}}
private static final java.util.List<Task> tasks=new java.util.ArrayList<>();private static long order;
private final Looper looper;
public Handler(Looper looper){this.looper=looper;}
public Looper getLooper(){return looper;}
public boolean post(Runnable action){return postDelayed(action,0);}
public boolean postDelayed(Runnable action,long delay){tasks.add(new Task(this,action,SystemClock.now+delay,order++));return true;}
public void removeCallbacks(Runnable action){tasks.removeIf(task->task.owner==this&&task.action==action);}
public static void reset(){tasks.clear();SystemClock.now=1000;}
public static void flushMain(){drain(SystemClock.now,Looper.MAIN);}
public static void advanceAll(long delay){drain(SystemClock.now+delay,null);}
private static void drain(long target,Looper filter){int budget=10000;
while(true){Task next=null;for(Task task:tasks)if(task.at<=target&&(filter==null||task.owner.looper==filter)
&&(next==null||task.at<next.at||task.at==next.at&&task.order<next.order))next=task;
if(next==null)break;if(--budget==0)throw new AssertionError("callback loop");tasks.remove(next);
SystemClock.now=Math.max(SystemClock.now,next.at);next.action.run();}SystemClock.now=target;}
}''',
    'android/os/PowerManager.java': '''package android.os;
public class PowerManager {public boolean interactive=true;public boolean isInteractive(){return interactive;}}''',
    'android/os/UserHandle.java': '''package android.os;
public class UserHandle {public static UserHandle of(int user){return new UserHandle();}}''',
    'android/app/ActivityManager.java': '''package android.app;
public class ActivityManager {public static int user;public static int getCurrentUser(){return user;}}''',
    'android/app/KeyguardManager.java': '''package android.app;
public class KeyguardManager {public boolean locked;public boolean isKeyguardLocked(){return locked;}}''',
    'android/view/InputEvent.java': 'package android.view; public class InputEvent {}',
    'android/view/InputDevice.java': '''package android.view;
public class InputDevice {public static final int SOURCE_STYLUS=0x4002,SOURCE_KEYBOARD=0x101,SOURCE_MOUSE=0x2002;
public String name="NVTCapacitivePenP81c",address;public int vendor,product;
public int getVendorId(){return vendor;}public int getProductId(){return product;}
public String getBluetoothAddress(){return address;}public String getName(){return name;}}''',
    'android/view/MotionEvent.java': '''package android.view;
public class MotionEvent extends InputEvent {
public static final int BUTTON_PRIMARY=1,ACTION_UP=1,ACTION_BUTTON_PRESS=11,ACTION_BUTTON_RELEASE=12;
public static final int ACTION_SCROLL=8,AXIS_VSCROLL=9,TOOL_TYPE_MOUSE=3;
public static class PointerProperties {public int id,toolType;}
public static class PointerCoords {public float x,y,scroll;public void setAxisValue(int axis,float value){scroll=value;}}
public PointerProperties properties;public PointerCoords coordinates;public boolean recycled;public int buttons,actionButton;public long downTime;
public void setActionButton(int value){actionButton=value;}
public static MotionEvent obtain(long down,long now,int action,int count,PointerProperties[] properties,PointerCoords[] coordinates,int meta,int buttons,float precisionX,float precisionY,int device,int edge,int source,int flags){MotionEvent event=new MotionEvent();event.action=action;event.source=source;event.properties=properties[0];event.coordinates=coordinates[0];event.buttons=buttons;event.downTime=down;return event;}
public void setDisplayId(int value){display=value;}public void recycle(){recycled=true;}
public static final int ACTION_DOWN=0,ACTION_MOVE=2,ACTION_CANCEL=3,ACTION_HOVER_MOVE=7,ACTION_HOVER_ENTER=9,ACTION_HOVER_EXIT=10;
public int action,source=InputDevice.SOURCE_STYLUS,display;public float rawX,rawY;
public InputDevice device=new InputDevice();
public InputDevice getDevice(){return device;}public boolean isFromSource(int expected){return (source&expected)==expected;}
public int getDisplayId(){return display;}public int getActionMasked(){return action;}
public float getX(){return 3;}public float getY(){return 5;}
public float getRawX(){return rawX;}public float getRawY(){return rawY;}
}''',
    'android/view/InputEventReceiver.java': '''package android.view;
public class InputEventReceiver {public static InputEventReceiver latest;public int finished;public boolean consumed,disposed;
public InputEventReceiver(Object channel,android.os.Looper looper){latest=this;}
public void onInputEvent(InputEvent event){}public void finishInputEvent(InputEvent event,boolean handled){finished++;consumed|=handled;}
public void dispose(){disposed=true;}}''',
    'android/view/InputMonitor.java': '''package android.view;
public class InputMonitor {public boolean disposed;public Object getInputChannel(){return this;}
public void dispose(){disposed=true;}}''',
    'android/hardware/input/InputManager.java': '''package android.hardware.input;
public class InputManager {public static final int INJECT_INPUT_EVENT_MODE_ASYNC=0;public int injected;
public final java.util.List<android.view.InputEvent> events=new java.util.ArrayList<>();
public android.view.InputEvent last;
public final java.util.List<Integer> targetUids=new java.util.ArrayList<>();public boolean rejectTarget;
public final android.view.InputMonitor monitor=new android.view.InputMonitor();
public android.view.InputMonitor monitorGestureInput(String name,int display){return monitor;}
public boolean injectInputEvent(android.view.InputEvent event,int mode){last=event;events.add(event);injected++;return true;}
public boolean injectInputEvent(android.view.InputEvent event,int mode,int uid){targetUids.add(uid);if(rejectTarget)return false;return injectInputEvent(event,mode);}}''',
    'android/view/KeyEvent.java': '''package android.view;
public class KeyEvent extends InputEvent {
public static final int KEYCODE_BACK=4,KEYCODE_HOME=3,KEYCODE_APP_SWITCH=187,KEYCODE_Z=54,KEYCODE_MEDIA_PLAY_PAUSE=85,
META_CTRL_ON=4096,META_CTRL_LEFT_ON=8192,META_SHIFT_ON=1,META_SHIFT_LEFT_ON=64,ACTION_DOWN=0,ACTION_UP=1,FLAG_FROM_SYSTEM=8,FLAG_CANCELED=32,
KEYCODE_UNKNOWN=0,KEYCODE_STYLUS_BUTTON_PRIMARY=308,KEYCODE_STYLUS_BUTTON_SECONDARY=309,KEYCODE_STYLUS_BUTTON_TERTIARY=310,
KEYCODE_PAGE_UP=92,KEYCODE_PAGE_DOWN=93;
public static final int KEYCODE_F1=131,KEYCODE_F2=132,KEYCODE_F3=133;
public final int action,code,flags,source;public final long downTime;public int display;
public KeyEvent(long down,long event,int action,int code,int repeat){this(down,event,action,code,repeat,0,-1,0,0,0);}
public KeyEvent(long down,long event,int action,int code,int repeat,int meta,int device,int scan,int flags,int source){
this.downTime=down;this.action=action;this.code=code;this.flags=flags;this.source=source;}
public void setDisplayId(int display){this.display=display;}
public static KeyEvent changeAction(KeyEvent original,int action){return new KeyEvent(original.downTime,original.downTime,action,original.code,0,0,-1,0,original.flags,original.source);}}''',
    'android/media/session/MediaSessionManager.java': '''package android.media.session;
public class MediaSessionManager {public void dispatchMediaKeyEvent(android.view.KeyEvent event,boolean wake){}}''',
    'android/view/WindowManager.java': '''package android.view;
public class WindowManager {public static final int TAKE_SCREENSHOT_FULLSCREEN=1;
public WindowMetrics getCurrentWindowMetrics(){return new WindowMetrics();}
public static class ScreenshotSource {public static final int SCREENSHOT_KEY_OTHER=1;}
public static class LayoutParams {
public static final int MATCH_PARENT=-1,TYPE_SYSTEM_OVERLAY=2006,FLAG_NOT_FOCUSABLE=8,FLAG_NOT_TOUCHABLE=16,FLAG_LAYOUT_IN_SCREEN=256;
public int gravity,flags,type;public String title;
public LayoutParams(int width,int height,int type,int flags,int format){this.type=type;this.flags=flags;}
public void setFitInsetsTypes(int types){}public void setTitle(String title){this.title=title;}}
public View attached;public LayoutParams params;public int adds,removes;public boolean failAdd;
public void addView(View view,LayoutParams params){if(failAdd)throw new IllegalArgumentException("injected add failure");
if(attached!=null)throw new AssertionError("duplicate overlay");attached=view;this.params=params;view.width=3048;view.height=2032;adds++;}
public void removeViewImmediate(View view){if(attached!=view)throw new IllegalArgumentException("not attached");attached=null;removes++;}
}''',
    'android/widget/Toast.java': '''package android.widget;
public class Toast {public static final int LENGTH_SHORT=0;
public static Toast makeText(android.content.Context context,String text,int duration){return new Toast();}public void show(){}}''',
    'com/android/internal/util/ScreenshotHelper.java': '''package com.android.internal.util;
public class ScreenshotHelper {public static int screenshots;
public ScreenshotHelper(android.content.Context context){}
public void takeScreenshot(int type,int source,android.os.Handler handler,Object consumer){screenshots++;}}''',
    'org/lineageos/sheng/pen/controls/PenControlsSettings.java': '''package org.lineageos.sheng.pen.controls;
public class PenControlsSettings {
public static final java.util.Map<PenControls.Gesture,PenControls.Action> actions=new java.util.HashMap<>();
public static int vibrationLevel=0;
public static String selectedApps;
public static int vibration(android.content.Context context,int user){return vibrationLevel;}
public static PenControls.Action action(android.content.Context context,PenControls.Gesture gesture,int user){return actions.getOrDefault(gesture,gesture.fallback);}
public static String read(android.content.Context context,String key,int user){return key.equals(PenControls.APP_OVERRIDES)?selectedApps:null;}}''',
    'org/lineageos/sheng/pen/controls/PenMenuApps.java': '''package org.lineageos.sheng.pen.controls;
public class PenMenuApps {public static void launch(android.content.Context context,PenMenuEntry entry,int user){}}''',
    'org/lineageos/sheng/stylus/PenShortcutMenu.java': '''package org.lineageos.sheng.stylus;
public class PenShortcutMenu {public static PenShortcutMenu latest;public boolean visible;public int toggles;
public java.util.function.Consumer<org.lineageos.sheng.pen.controls.PenMenuEntry> selected;
public org.lineageos.sheng.pen.controls.PenMenuEntry[] entries;
public PenShortcutMenu(android.content.Context context,android.os.Handler handler,
java.util.function.Consumer<org.lineageos.sheng.pen.controls.PenMenuEntry> selected){latest=this;this.selected=selected;}
public void toggle(org.lineageos.sheng.pen.controls.PenMenuEntry[] entries,float screenX,float screenY){this.entries=entries;toggles++;visible=!visible;}
public void hide(){visible=false;}}''',
    'android/graphics/Rect.java': '''package android.graphics;
public class Rect {public float exactCenterX(){return 1524;}public float exactCenterY(){return 1016;}}''',
    'android/view/WindowMetrics.java': '''package android.view;
public class WindowMetrics {public android.graphics.Rect getBounds(){return new android.graphics.Rect();}}''',
}
