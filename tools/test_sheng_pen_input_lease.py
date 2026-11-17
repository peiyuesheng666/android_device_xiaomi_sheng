#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Test real lease code and Android AtomicFile/JSON with a host input-service double."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

DEVICE = Path(__file__).resolve().parents[1]
ROM = Path(os.environ.get('SHENG_ROM_ROOT', '/root/sheng-pixelos/android'))
OUT = ROM / os.environ.get('SHENG_ROM_OUT', 'out-clean-ota-20261116')
ROOT = DEVICE.parents[2]/'reports/device/20261114-stylus-service'
ROOT.mkdir(parents=True, exist_ok=True)
WORK = Path(tempfile.mkdtemp(prefix='input-lease-test-', dir=ROOT))
os.environ.update(LANG='C.UTF-8', LC_ALL='C.UTF-8')
fixtures = {
'android/content/ContentResolver.java': 'package android.content; public class ContentResolver {public int boot=1;}',
'android/content/Context.java': '''package android.content;
import java.io.File;public class Context{public final File files;public final ContentResolver resolver=new ContentResolver();
public Context(File f){files=f;}public Context createDeviceProtectedStorageContext(){return this;}public File getFilesDir(){return files;}public ContentResolver getContentResolver(){return resolver;}}
''',
'android/provider/Settings.java': '''package android.provider;
import android.content.ContentResolver;public class Settings{public static class Global{public static final String BOOT_COUNT="boot_count";public static int getInt(ContentResolver resolver,String key,int fallback){return resolver.boot;}}}
''',
'android/os/ServiceManager.java': 'package android.os; public class ServiceManager{public static Object service;public static Object getService(String name){return service;}}',
'android/os/SystemClock.java': 'package android.os; public class SystemClock{public static long uptimeMillis(){return System.nanoTime()/1000000;}}',
'android/os/FileUtils.java': '''package android.os;
import java.io.FileOutputStream;public class FileUtils{public static final int S_IRWXU=0700,S_IRWXG=0070,S_IXOTH=0001;
public static int setPermissions(String path,int mode,int uid,int gid){return 0;}public static boolean sync(FileOutputStream file){try{file.getFD().sync();return true;}catch(Exception error){return false;}}}
''',
'libcore/io/IoUtils.java': 'package libcore.io;public class IoUtils{public static void closeQuietly(AutoCloseable value){try{if(value!=null)value.close();}catch(Exception error){}}}',
'android/util/Log.java': 'package android.util;public class Log{public static int e(String tag,String text){return 0;}public static int e(String tag,String text,Throwable error){return 0;}}',
'android/view/InputDevice.java': '''package android.view;
public class InputDevice{public static final int SOURCE_MOUSE=0x2002,SOURCE_KEYBOARD=0x101;public int sources=SOURCE_KEYBOARD;public int getSources(){return sources;}public int id,vendor=34,product=0x5081;public String address="28:CE:15:31:70:0E",descriptor="owned-pro";public boolean enabled=true;
public InputDevice(int id){this.id=id;}public int getVendorId(){return vendor;}public int getProductId(){return product;}public String getBluetoothAddress(){return address;}public String getDescriptor(){return descriptor;}public boolean isEnabled(){return enabled;}}
''',
'android/hardware/input/IInputManager.java': '''package android.hardware.input;
import android.view.InputDevice;public interface IInputManager{int[] getInputDeviceIds()throws Exception;InputDevice getInputDevice(int id)throws Exception;void enableInputDevice(int id)throws Exception;void disableInputDevice(int id)throws Exception;
public static class Stub{public static IInputManager asInterface(Object object){return (IInputManager)object;}}}
''',
'org/lineageos/sheng/stylus/PenInputLeaseTest.java': '''package org.lineageos.sheng.stylus;
import android.content.Context;import android.hardware.input.IInputManager;import android.os.ServiceManager;import android.view.InputDevice;
import java.io.*;import java.nio.file.*;import java.nio.charset.StandardCharsets;import java.util.*;import org.json.*;
public class PenInputLeaseTest {
 static int checks;static Path root;
 static void check(boolean value,String reason){checks++;if(!value)throw new AssertionError(reason);}
 interface Checked{void run()throws Exception;}
 static void rejects(Checked action,String reason)throws Exception{try{action.run();}catch(Exception expected){checks++;return;}throw new AssertionError(reason);}
 static class Manager implements IInputManager{
  Map<Integer,InputDevice> devices=new LinkedHashMap<>();Set<Integer> disabled=new HashSet<>();List<Integer> enables=new ArrayList<>();
  boolean disableApplies=true,enableApplies=true,disableThrows;int disables;Context context;
  public int[] getInputDeviceIds(){return devices.keySet().stream().mapToInt(Integer::intValue).toArray();}
  public InputDevice getInputDevice(int id){return devices.get(id);}
  public void disableInputDevice(int id)throws Exception{
   JSONObject saved=read(context);boolean committed=false;
   JSONArray entries=saved.getJSONArray("entries");for(int i=0;i<entries.length();i++){JSONArray ids=entries.getJSONObject(i).getJSONArray("ownedIds");for(int j=0;j<ids.length();j++)if(ids.getInt(j)==id)committed=true;}
   check(committed,"owned intent must reach disk before disable Binder call");
   if(disableThrows)throw new IOException("injected Binder failure");disables++;disabled.add(id);if(disableApplies&&devices.containsKey(id))devices.get(id).enabled=false;
  }
  public void enableInputDevice(int id){enables.add(id);disabled.remove(id);if(enableApplies&&devices.containsKey(id))devices.get(id).enabled=true;}
 }
 static class Run{Context context;Manager manager=new Manager();PenInputLease lease;
  Run()throws Exception{context=new Context(Files.createTempDirectory(root,"lease-").toFile());manager.context=context;ServiceManager.service=manager;lease=new PenInputLease(context,new File(context.files,"keylayout"));}
  InputDevice target(int id){InputDevice device=new InputDevice(id);manager.devices.put(id,device);return device;}
  void guard()throws Exception{lease.guard(PenModel.PRO,0x5081,"28:CE:15:31:70:0E");}
 }
 static JSONObject read(Context context)throws Exception{return new JSONObject(Files.readString(new File(context.files,"pro-input-lease.json").toPath()));}
 static int entries(Run run)throws Exception{return read(run.context).getJSONArray("entries").length();}
 static void identityAndPriorState()throws Exception{
  Run r=new Run();InputDevice target=r.target(3);InputDevice other=r.target(4);other.address="28:CE:15:31:70:0F";other.descriptor="other-pro";
  InputDevice keyboard=r.target(5);keyboard.product=0x3282;InputDevice vendor=r.target(6);vendor.vendor=33;
  r.guard();check(!target.enabled&&other.enabled&&keyboard.enabled&&vendor.enabled,"only exact Pro identity disabled");
  check(r.manager.disables==1&&entries(r)==1,"one owned journal entry");
  check(r.lease.restore()&&target.enabled&&entries(r)==0,"owned input enabled and journal cleared");
  check(r.manager.enables.equals(Arrays.asList(3)),"restore cannot enable unrelated IDs");
  r=new Run();target=r.target(3);target.enabled=false;r.guard();check(entries(r)==0,"already disabled input never claimed");
  r.lease.restore();check(!target.enabled&&r.manager.enables.isEmpty(),"pre-existing external disable preserved");
  r=new Run();r.target(3);r.lease.guard(PenModel.FOCUS,0x4d80,"28:CE:15:31:70:0E");check(r.manager.disables==0&&entries(r)==0,"ordinary guard never disables a Pro companion");
 }
 static void ordinaryCompanion()throws Exception{
  for(int product:new int[]{0x4d80,0x3280}){
   Run r=new Run();InputDevice companion=r.target(3);companion.product=product;companion.descriptor="ordinary-companion";
   InputDevice physical=r.target(4);physical.vendor=0;physical.product=0;physical.address="";physical.descriptor="NVTCapacitivePenP81c";
   InputDevice other=r.target(5);other.product=product;other.address="28:CE:15:31:70:0F";other.descriptor="other-ordinary";
   InputDevice pro=r.target(6);
   check(r.lease.guard(PenModel.FOCUS,product,"28:CE:15:31:70:0E"),"ordinary companion disabled and acknowledged");
   check(!companion.enabled&&physical.enabled&&other.enabled&&pro.enabled,"ordinary plus guard preserves physical writing, other pen and Pro");
   check(r.manager.disables==1&&entries(r)==1,"ordinary companion has one durable restoration entry");
   check(r.lease.restore()&&companion.enabled&&physical.enabled&&entries(r)==0,"ordinary restore preserves physical writing");
   check(r.manager.enables.equals(Arrays.asList(3)),"ordinary restore touches only its owned companion ID");
  }
 }
 static void asynchronousAndAbsent()throws Exception{
  Run r=new Run();r.target(3);r.manager.disableApplies=false;r.guard();
  check(r.manager.disabled.contains(3)&&r.manager.devices.get(3).enabled,"reader has not applied pending disable yet");
  check(r.lease.restore()&&r.manager.disabled.isEmpty()&&r.manager.enables.equals(Arrays.asList(3)),"restore cancels pending disable even while reader says enabled");
  r=new Run();r.target(3);r.guard();r.manager.devices.remove(3);
  check(r.lease.restore()&&!r.manager.disabled.contains(3)&&entries(r)==0,"absent owned ID removed from retained native disabled set");
  r=new Run();r.target(3);r.guard();r.manager.enableApplies=false;
  check(!r.lease.restore()&&entries(r)==1,"asynchronous enable debt retained while reader remains disabled");
  r.manager.enableApplies=true;check(r.lease.restore()&&entries(r)==0,"later enable acknowledgement retires debt");
 }
 static void reconnectAndCrash()throws Exception{
  Run r=new Run();r.target(3);r.guard();r.manager.devices.remove(3);r.target(33);r.guard();
  JSONArray ids=read(r.context).getJSONArray("entries").getJSONObject(0).getJSONArray("ownedIds");
  check(ids.length()==2&&r.manager.disabled.containsAll(Arrays.asList(3,33)),"every new disabled reader ID journalled before reuse");
  r.lease=new PenInputLease(r.context);check(r.lease.restore()&&r.manager.disabled.isEmpty(),"replacement client restores present and absent owned IDs");
  check(r.manager.devices.get(33).enabled&&entries(r)==0,"reconnected owned input enabled");
  r=new Run();r.target(3);r.guard();r.manager.devices.remove(3);InputDevice reused=r.target(3);reused.address="28:CE:15:31:70:0F";reused.enabled=false;
  check(!r.lease.restore()&&r.manager.enables.isEmpty()&&entries(r)==1,"recycled ID with another MAC cannot be enabled");
  r.manager.devices.remove(3);check(r.lease.restore()&&entries(r)==0,"recycled ID debt drains only after unrelated input is absent");
 }
 static void writeFailureAndBoot()throws Exception{
  Run r=new Run();InputDevice target=r.target(3);Files.createDirectory(new File(r.context.files,"pro-input-lease.json.new").toPath());
  Run failed=r;rejects(failed::guard,"failed journal must reject disable");
  check(target.enabled&&r.manager.disables==0,"commit failure performs no input disable");
  r=new Run();r.target(3);r.manager.disableThrows=true;Run binderFailure=r;rejects(binderFailure::guard,"Binder failure expected");
  check(entries(r)==1&&r.manager.devices.get(3).enabled,"committed intent survives pre-disable Binder failure");
  r.manager.disableThrows=false;r.lease=new PenInputLease(r.context);check(r.lease.restore()&&entries(r)==0,"committed but unapplied intent safely restored");
  r=new Run();target=r.target(3);r.guard();r.context.resolver.boot=2;r.manager.disabled.clear();r.manager.enables.clear();target.enabled=false;
  r.lease=new PenInputLease(r.context);r.lease.restore();check(entries(r)==0&&r.manager.enables.isEmpty()&&!target.enabled,"old boot journal cannot enable newly externally disabled input");
  r=new Run();Files.writeString(new File(r.context.files,"pro-input-lease.json").toPath(),"{broken",StandardCharsets.UTF_8);Run malformed=r;
  rejects(()->new PenInputLease(malformed.context),"corrupt journal must fail closed");check(r.manager.disables==0&&r.manager.enables.isEmpty(),"corrupt journal changes no input state");
 }
 static void pointerMode()throws Exception{
  for(int product:new int[]{0x4d80,0x3280,0x5081,0x3281}){
   Run run=new Run();PenModel model=PenModel.fromBluetoothIds(34,product);
   InputDevice mouse=run.target(11);mouse.product=product;mouse.sources=InputDevice.SOURCE_MOUSE;mouse.descriptor="mouse";
   InputDevice keyboard=run.target(12);keyboard.product=product;keyboard.descriptor="keyboard";
   InputDevice mixed=run.target(13);mixed.product=product;mixed.sources=InputDevice.SOURCE_MOUSE|InputDevice.SOURCE_KEYBOARD;mixed.descriptor="mixed";
   InputDevice external=run.target(14);external.product=product;external.sources=InputDevice.SOURCE_MOUSE;external.address="28:CE:15:31:70:0F";
   run.lease.guard(model,product,mouse.address);
   check(!mouse.enabled&&!keyboard.enabled&&!mixed.enabled&&external.enabled,"idle suppresses only this pen's companion inputs");
   run.manager.enables.clear();run.lease.setPointerEnabled(true);
   check(run.lease.guard(model,product,mouse.address),"mouse transition acknowledged");
   check(mouse.enabled&&!keyboard.enabled&&!mixed.enabled&&external.enabled,"pointer restores pure mouse only; keyboard plus suppression retained");
   check(run.manager.enables.equals(Arrays.asList(11)),"mouse enable never enables keyboard or other address");
   Path layouts=new File(run.context.files,"keylayout").toPath();Files.createDirectory(layouts);
   Path layout=layouts.resolve(String.format(java.util.Locale.ROOT,"Vendor_0022_Product_%04x.kl",product));
   Files.writeString(layout,"key 0 UNKNOWN\\n");
   check(run.lease.guard(model,product,mouse.address)&&mixed.enabled&&!keyboard.enabled,"merged Android mouse/keyboard allowed only with packaged suppression layout");
   Files.writeString(layout,"key 78 NUMPAD_ADD\\n");run.lease.guard(model,product,mouse.address);
   check(!mixed.enabled&&mouse.enabled,"wrong layout fails closed instead of reintroducing plus input");
   run.lease.setPointerEnabled(false);run.lease.guard(model,product,mouse.address);
   check(!mouse.enabled&&!keyboard.enabled,"leaving mouse mode disables mouse again");
   run.lease.setPointerEnabled(true);run.manager.enableApplies=false;
   check(!run.lease.guard(model,product,mouse.address),"async mouse enable is not falsely acknowledged");
   run.manager.enableApplies=true;check(run.lease.guard(model,product,mouse.address)&&mouse.enabled,"async enable retries without losing debt");
   check(run.lease.restore()&&mouse.enabled&&keyboard.enabled&&mixed.enabled,"session exit restores all owned inputs");
   mouse.enabled=false;run.lease.setPointerEnabled(true);run.lease.guard(model,product,mouse.address);
   check(!mouse.enabled,"external mouse disable is never overridden");
  }
 }
 public static void main(String[] args)throws Exception{root=Path.of(args[0]);identityAndPriorState();ordinaryCompanion();asynchronousAndAbsent();reconnectAndCrash();writeFailureAndBoot();pointerMode();System.out.println("PASS input_lease_checks="+checks+" hardware_tested=false framework_input_service_tested=false");}
}
'''
}
sources=[]
for relative, body in fixtures.items():
    path=WORK/'fixtures'/relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body,encoding='utf-8')
    sources.append(path)
actual=[DEVICE/'interfaces/input/stylus/app/org/lineageos/sheng/stylus/PenInputLease.java',
        DEVICE/'interfaces/input/stylus/app/org/lineageos/sheng/stylus/PenInputIdentity.java',
        DEVICE/'interfaces/input/stylus/src/org/lineageos/sheng/stylus/PenModel.java']
framework=OUT/'soong/.intermediates/frameworks/base/framework-minus-apex/android_common/combined/framework.jar'
libcore=OUT/'soong/.intermediates/libcore/core-libart/android_common_apex31/javac/core-libart.jar'
classpath=os.pathsep.join(map(str,[framework,libcore]))
jdk=ROM/'prebuilts/jdk/jdk21/linux-x86/bin'
compile_result=subprocess.run([jdk/'javac','-encoding','UTF-8','-cp',classpath,'-d',WORK/'classes',*sources,*actual],text=True,capture_output=True)
receipt=dict(date_utc=datetime.now(timezone.utc).isoformat(),kind='actual-input-lease-atomicfile-host-harness',
             actual_source_sha256={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in actual},
             framework_jar=str(framework),framework_sha256=hashlib.sha256(framework.read_bytes()).hexdigest(),
             compiled=compile_result.returncode==0,compile_stderr=compile_result.stderr,
             hardware_tested=False,framework_input_service_tested=False,android_atomicfile_implementation_used=True)
if compile_result.returncode==0:
    result=subprocess.run([jdk/'java','-cp',os.pathsep.join(map(str,[WORK/'classes',framework,libcore])),
                           'org.lineageos.sheng.stylus.PenInputLeaseTest',WORK],text=True,capture_output=True)
    receipt.update(passed=result.returncode==0,stdout=result.stdout,stderr=result.stderr,exit_code=result.returncode)
else: receipt.update(passed=False,exit_code=compile_result.returncode)
(WORK/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(WORK)
print(json.dumps(receipt,indent=2))
raise SystemExit(0 if receipt['passed'] else 1)
