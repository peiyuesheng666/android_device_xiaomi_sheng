#!/usr/bin/env python3
"""Exercise the production controller against a deterministic asynchronous DMS model."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

STUBS = {
    'android/content/SharedPreferences.java': '''package android.content;
public interface SharedPreferences {
 boolean getBoolean(String k, boolean d); int getInt(String k,int d); String getString(String k,String d);
 Editor edit(); interface Editor { Editor putBoolean(String k,boolean v); Editor putInt(String k,int v);
 Editor putString(String k,String v); Editor remove(String k); void apply(); }
}''',
    'android/content/Context.java': '''package android.content;
import java.util.HashMap;
public class Context {
 public static final int MODE_PRIVATE=0;
 public static final HashMap<String,Object> values=new HashMap<>();
 public Context createDeviceProtectedStorageContext(){return this;}
 public SharedPreferences getSharedPreferences(String name,int mode){return new Prefs();}
 static final class Prefs implements SharedPreferences {
  public boolean getBoolean(String k,boolean d){return values.containsKey(k)?(Boolean)values.get(k):d;}
  public int getInt(String k,int d){return values.containsKey(k)?(Integer)values.get(k):d;}
  public String getString(String k,String d){return values.containsKey(k)?(String)values.get(k):d;}
  public Editor edit(){return new Changes();}
 }
 static final class Changes implements SharedPreferences.Editor {
  private final HashMap<String,Object> pending=new HashMap<>();
  public SharedPreferences.Editor putBoolean(String k,boolean v){pending.put(k,v);return this;}
  public SharedPreferences.Editor putInt(String k,int v){pending.put(k,v);return this;}
  public SharedPreferences.Editor putString(String k,String v){pending.put(k,v);return this;}
  public SharedPreferences.Editor remove(String k){pending.put(k,null);return this;}
  public void apply(){for(String k:pending.keySet()){if(pending.get(k)==null)values.remove(k);else values.put(k,pending.get(k));}}
 }
}''',
    'android/content/ContextWrapper.java': '''package android.content;
public class ContextWrapper extends Context { public ContextWrapper(Context context){} }''',
    'android/os/Looper.java': '''package android.os; public final class Looper {}''',
    'android/os/HandlerThread.java': '''package android.os;
public final class HandlerThread {public HandlerThread(String name){} public void start(){}
 public Looper getLooper(){return new Looper();}}''',
    'android/os/Handler.java': '''package android.os;
import java.util.PriorityQueue;
public final class Handler {
 private static long now,serial;
 private static final PriorityQueue<Job> jobs=new PriorityQueue<>();
 private static final class Job implements Comparable<Job> {
  final long at,order; final Runnable task;
  Job(long at,Runnable task){this.at=at;this.task=task;order=serial++;}
  public int compareTo(Job b){int c=Long.compare(at,b.at);return c==0?Long.compare(order,b.order):c;}
 }
 public Handler(Looper l){} public boolean post(Runnable r){return postDelayed(r,0);}
 public boolean postDelayed(Runnable r,long delay){jobs.add(new Job(now+delay,r));return true;}
 public void removeCallbacks(Runnable r){jobs.removeIf(j->j.task==r);}
 public static void reset(){jobs.clear();now=serial=0;}
 public static void advance(long delay){long end=now+delay;int count=0;
  while(!jobs.isEmpty()&&jobs.peek().at<=end){Job j=jobs.remove();now=j.at;j.task.run();
   if(++count>10000)throw new AssertionError("Unbounded scheduling");}now=end;}
}''',
    'android/os/RemoteException.java': '''package android.os; public class RemoteException extends Exception {}''',
    'android/os/IBinder.java': '''package android.os;
public interface IBinder { boolean isBinderAlive();void linkToDeath(DeathRecipient r,int flags)throws RemoteException;
 interface DeathRecipient{void binderDied();}}''',
    'android/os/ServiceManager.java': '''package android.os;
import java.util.ArrayList;
public final class ServiceManager {
 public static Binder current=new Binder();
 public static IBinder checkService(String name){return current;}
 public static final class Binder implements IBinder {
  private final ArrayList<DeathRecipient> clients=new ArrayList<>();private boolean alive=true;
  public boolean isBinderAlive(){return alive;}
  public void linkToDeath(DeathRecipient r,int flags)throws RemoteException{clients.add(r);}
  public void die(){alive=false;ServiceManager.current=new Binder();
   for(DeathRecipient r:clients)r.binderDied();}
 }
}''',
    'android/util/Log.java': '''package android.util;
import java.util.ArrayList;
public final class Log {public static final ArrayList<String> warnings=new ArrayList<>();
 public static int i(String t,String m){return 0;}
 public static int w(String t,String m,Throwable e){warnings.add(m+": "+e);return 0;}}''',
    'android/media/audiofx/AudioEffect.java': '''package android.media.audiofx;
import java.nio.ByteBuffer;import java.nio.ByteOrder;import java.util.HashMap;import java.util.UUID;
public final class AudioEffect {
 public static final int SUCCESS=0;public static int selected,gainWrites;public static boolean enabled,badReadback;
 public static final HashMap<String,int[]> values=new HashMap<>();
 public boolean released,control=true;private OnControlStatusChangeListener listener;
 public AudioEffect(UUID type,UUID impl,int priority,int session){}
 public interface OnControlStatusChangeListener{void onControlStatusChange(AudioEffect e,boolean control);}
 public void setControlStatusListener(OnControlStatusChangeListener listener){this.listener=listener;}
 public boolean hasControl(){return control&&!released;}public void release(){released=true;}
 public boolean getEnabled(){return enabled;}public int setEnabled(boolean on){enabled=on;return 0;}
 public static void reset(){selected=gainWrites=0;enabled=badReadback=false;values.clear();}
 public static int[] value(int profile,int parameter){int[] v=values.get(profile+":"+parameter);
  return v==null?(parameter==110?new int[20]:new int[]{parameter==104?1:parameter==108?6:0}):v.clone();}
 public int setParameter(int key,byte[] bytes){ByteBuffer b=ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
  int op=b.getInt()>>>24;b.getInt();int arg=b.getInt();
  if(op==0)enabled=arg!=0;
  else if(op==10)selected=arg;
  else if(op==12){for(int p:new int[]{104,105,106,108,110})values.remove(arg+":"+p);}
  else if(op==1){int parameter=b.getInt();int[] data=new int[b.remaining()/4];for(int i=0;i<data.length;i++)data[i]=b.getInt();
   values.put(arg+":"+parameter,data);if(parameter==110)gainWrites++;}
  else throw new AssertionError("Unexpected opcode "+op);return 0;
 }
 public int getParameter(int key,byte[] bytes){int op=key>>>24;int[] data;
  if(op==0)data=new int[]{enabled?1:0};else if(op==10)data=new int[]{selected};
  else if(op==1){int parameter=(key>>>16)&255;data=value((key>>>8)&255,parameter);
   if(badReadback&&parameter==110)data[0]+=64;}
  else throw new AssertionError("Unexpected query "+op);
  ByteBuffer b=ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);for(int v:data)b.putInt(v);return data.length*4;
 }
}''',
    'org/lineageos/sheng/dolby/EditTest.java': '''package org.lineageos.sheng.dolby;
import android.content.Context;import android.media.audiofx.AudioEffect;import android.os.Handler;
import android.os.ServiceManager;import android.util.Log;import java.util.Arrays;
public final class EditTest {
 static int checks;
 static void require(boolean ok,String name){if(!ok)throw new AssertionError(name);checks++;}
 static AtmosApplication ready(){Handler.reset();Context.values.clear();AudioEffect.reset();Log.warnings.clear();
  ServiceManager.current=new ServiceManager.Binder();Context.values.put("enabled",true);Context.values.put("profile",3);
  AtmosApplication app=new AtmosApplication(new Context());Handler.advance(200);
  require(app.getState().ready&&app.getState().profile==3,"Controller startup");return app;}
 static void band(AtmosApplication app,int index,int gain){
  try {app.getClass().getMethod("setBandGain",int.class,int.class).invoke(app,index,gain);}
  catch(NoSuchMethodException legacy){int[] v=app.getState().gains.clone();
   for(int i=index*4;i<index*4+4;i++)v[i]=gain;app.setParameter(110,v);}
  catch(Exception e){throw new AssertionError(e);}}
 static void nativeBands(int... gains){int[] expected=new int[20];for(int i=0;i<5;i++)Arrays.fill(expected,i*4,i*4+4,gains[i]);
  require(Arrays.equals(expected,AudioEffect.value(3,110)),"Rapid grouped edits must retain all requested bands");}
 static void quiet(String scenario){require(Log.warnings.isEmpty(),scenario+" produced "+Log.warnings);}
 public static void main(String[] args){
  AtmosApplication app=ready();int count=AudioEffect.gainWrites;
  band(app,0,384);band(app,1,-192);band(app,4,128);Handler.advance(200);
  nativeBands(384,-192,0,0,128);require(AudioEffect.gainWrites-count==1,"Coalesce queued native writes");
  require(Context.values.get("param.3.110").equals("384,384,384,384,-192,-192,-192,-192,0,0,0,0,0,0,0,0,128,128,128,128"),"Save final merged vector");
  quiet("rapid cross-band edits");
  app=ready();band(app,0,384);Handler.advance(0);app.resetProfile();Handler.advance(200);
  nativeBands(0,0,0,0,0);require(!Context.values.containsKey("param.3.110"),"Reset cannot resurrect pending saved EQ");quiet("pending readback reset");
  app=ready();band(app,0,384);Handler.advance(200);app.resetProfile();band(app,4,-128);Handler.advance(200);
  nativeBands(0,0,0,0,-128);quiet("reset followed by immediate edit");
  app=ready();band(app,0,384);Handler.advance(0);app.setProfile(0);Handler.advance(200);
  require(Context.values.containsKey("param.3.110"),"Mode change must retain confirmed edits in the previous profile");require(app.getState().profile==0,"Latest mode wins");quiet("mode change");
  app=ready();band(app,0,384);Handler.advance(0);app.setProfile(0);app.setProfile(3);Handler.advance(200);
  nativeBands(384,0,0,0,0);require(Context.values.containsKey("param.3.110"),"Rapid mode round-trip retains and confirms the latest vector");quiet("rapid mode round-trip");
  app=ready();for(int i=0;i<1000;i++)band(app,i%5,(i%13-6)*64);Handler.advance(200);
  quiet("1000 queued edits");require(AudioEffect.gainWrites==2,"Only startup and final burst vector reach native DMS");
  app=ready();int[] external=new int[20];external[0]=64;app.setParameter(110,external);external[0]=384;Handler.advance(200);
  require(AudioEffect.value(3,110)[0]==64,"Request data is immutable");
  app=ready();AudioEffect.badReadback=true;band(app,0,384);Handler.advance(200);
  require(app.getState().failed&&!Log.warnings.isEmpty(),"Real persistent mismatch must remain visible");
  app=ready();band(app,2,192);Handler.advance(200);ServiceManager.current.die();AudioEffect.reset();Handler.advance(1200);
  nativeBands(0,0,192,0,0);require(app.getState().ready&&!app.getState().failed,"Restore confirmed settings after audio server replacement");quiet("server replacement");
  app.setRequested(false);Handler.advance(200);require(!app.getState().requested&&!AudioEffect.enabled,"Master off");
  app.setRequested(true);Handler.advance(200);require(app.getState().active,"Master on");
  System.out.println("PASS "+checks+" checks: merged edits, reset invalidation, immediate edits, mode changes, burst coalescing, defensive copies, failure visibility, audio-server restoration, master controls");
 }
}''',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--source-dir', type=Path, help='Candidate Java package directory')
    parser.add_argument('--against-head', action='store_true', help='Verify that the previous controller exposes the regression')
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=False)
    device = Path(__file__).resolve().parents[1]
    java = Path('/root/sheng-lineage/lineage-24.0/prebuilts/jdk/jdk21/linux-x86/bin')
    inputs = []
    for name, source in STUBS.items():
        path = args.work/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
        inputs.append(path)
    source_dir = args.source_dir or device/'docs/candidates/dolby-r53/source/src/org/lineageos/sheng/dolby'
    for name in ['AtmosApplication.java', 'StockDms.java', 'ParameterEdits.java']:
        path = source_dir/name
        if args.against_head and name == 'AtmosApplication.java':
            relative = 'device/xiaomi/sheng/dolby/ShengDolby/src/org/lineageos/sheng/dolby/'+name
            path = args.work/'original'/name
            path.parent.mkdir()
            path.write_bytes(subprocess.check_output(['git','-C',str(device),'show','HEAD:'+relative]))
        inputs.append(path)
    classes = args.work/'classes'
    classes.mkdir()
    env = dict(os.environ,LANG='C.UTF-8',LC_ALL='C.UTF-8')
    subprocess.run(list(map(str,[java/'javac','-encoding','UTF-8','-d',classes,*inputs])),env=env,check=True)
    result = subprocess.run([str(java/'java'),'-cp',str(classes),'org.lineageos.sheng.dolby.EditTest'],
                            env=env,capture_output=True,text=True)
    receipt = dict(passed=result.returncode==0,against_head=args.against_head,returncode=result.returncode,
                   stdout=result.stdout,stderr=result.stderr,
                   sources_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs})
    (args.work/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(result.stdout+result.stderr)
    if args.against_head:
        assert result.returncode != 0 and 'Rapid grouped edits' in result.stderr, 'Regression did not reproduce'
        print('PASS: previous production controller reproduced the cross-band regression')
    else:
        assert result.returncode == 0, 'Controller tests failed'


if __name__ == '__main__':
    main()
