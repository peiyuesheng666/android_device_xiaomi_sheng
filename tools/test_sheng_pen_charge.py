#!/usr/bin/env python3
"""Check charger sentinels and attachment boundaries without simulating a charge."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

workspace = Path(__file__).resolve().parents[4]
os.environ.update(LANG='C.UTF-8', LC_ALL='C.UTF-8')
source = workspace/'device/xiaomi/sheng/interfaces/input/pen/common/org/lineageos/sheng/pen/charge/ChargeStatus.java'
acquisition_source = source.with_name('ChargeAcquisition.java')
session_source = workspace/'device/xiaomi/sheng/interfaces/input/stylus/app/org/lineageos/sheng/stylus/PenChargeSession.java'
work = Path(tempfile.mkdtemp(prefix='charge-state-test-', dir=workspace/'reports/device/20261114-stylus-service'))
test = work/'ChargeStateTest.java'
test.write_text('''package org.lineageos.sheng.stylus;
import org.lineageos.sheng.pen.charge.ChargeStatus;
import org.lineageos.sheng.pen.charge.ChargeAcquisition;
public class ChargeStateTest {
 static int checks;
 static void check(boolean condition) { ++checks; if(!condition)throw new AssertionError("check "+checks); }
 static ChargeStatus read(String a,String b,String mode,String level,String peer,String error) {
  return ChargeStatus.decode(a,b,mode,level,peer,error);
 }
 public static void main(String[] args) {
  String peer="28ce1531700e";
  check(ChargeStatus.address(peer).equals("28CE1531700E"));
  check(ChargeStatus.address("28:ce:15:31:70:0e").equals("28CE1531700E"));
  for(String invalid:new String[]{"255","ff","000000000000","ffffffffffff","garbage","28:xx:15:31:70:0e","1234567890123",""})check(ChargeStatus.address(invalid)==null);
  check(read("0","1","4","99",peer,"0").charging());
  check(read("1","0","4","100",peer,"0").state==ChargeStatus.State.FULL);
  check(read("1","1","4","99",peer,"0").state==ChargeStatus.State.DETACHED);
  check(read("1","1","4","99",peer,"0").level==-1);
  check(read("2","1","4","99",peer,"0").state==ChargeStatus.State.UNKNOWN);
  check(read("","1","4","99",peer,"0").state==ChargeStatus.State.UNKNOWN);
  check(read("0","1","4","99",peer,"1").state==ChargeStatus.State.MISALIGNED);
  for(String level:new String[]{"255","101","-1","unknown"})check(read("0","1","4",level,peer,"0").level==-1);
  for(String mode:new String[]{"0","1","2","3","5","unknown"})check(!read("0","1",mode,"99",peer,"0").charging());
  check(!read("0","1","4","99","255","0").charging());
  check(!read("0","1","4","99","","0").charging());
  check(ChargeStatus.unknown().level==-1 && !ChargeStatus.unknown().docked());
  check(ChargeStatus.fromProvider("CHARGING",99,peer).charging());
  check(ChargeStatus.fromProvider("FULL",100,peer).state==ChargeStatus.State.FULL);
  for(String name:new String[]{"garbage","FULL","CHARGING"})check(ChargeStatus.fromProvider(name,255,peer).state==ChargeStatus.State.UNKNOWN);
  check(ChargeStatus.fromProvider("FULL",99,peer).state==ChargeStatus.State.UNKNOWN);
  check(ChargeStatus.fromProvider("CHARGING",100,peer).state==ChargeStatus.State.UNKNOWN);
  check(ChargeStatus.fromProvider("DETACHED",99,peer).level==-1);
  check(read("0","1","2","255","","0").state==ChargeStatus.State.NOT_CHARGING);
  check(read("0","1","0","255","","0").state==ChargeStatus.State.NOT_CHARGING);
  check(ChargeStatus.fromProvider("NOT_CHARGING",255,peer).level==-1);
  check(ChargeStatus.read(name -> {
   if(name.equals("pen_hall3") || name.equals("pen_place_err"))return "0";
   if(name.equals("pen_hall4"))return "1";
   if(name.equals("reverse_chg_state"))return "2";
   throw new java.io.IOException("Stopped charger has no peer/battery data");
  }).state==ChargeStatus.State.NOT_CHARGING);
  check(ChargeStatus.read(name -> {
   if(name.equals("pen_hall3") || name.equals("pen_hall4"))return "1";
   throw new java.io.IOException("Undocked charging attribute unavailable");
  }).state==ChargeStatus.State.DETACHED);
  final int[] halls={0};
  check(ChargeStatus.read(name -> {
   if(name.equals("pen_hall3"))return halls[0]++==0 ? "1" : "0";
   if(name.equals("pen_hall4"))return "1";
   throw new java.io.IOException("No charging detail available");
  }).state==ChargeStatus.State.UNKNOWN);
  check(ChargeStatus.read(name -> {throw new java.io.IOException("Hall unavailable");}).state==ChargeStatus.State.UNKNOWN);
  java.util.Map<String,String> nodes=new java.util.HashMap<>();
  nodes.put("pen_hall3","0");nodes.put("pen_hall4","1");nodes.put("pen_mac",peer);
  nodes.put("reverse_chg_state","4");nodes.put("pen_soc","99");nodes.put("pen_place_err","0");
  check(ChargeStatus.read(nodes::get).charging());
  nodes.put("pen_mac", "");
  check(ChargeStatus.read(nodes::get).state==ChargeStatus.State.WAITING);
  nodes.put("pen_mac",peer);
  final int[] modes={0};
  check(ChargeStatus.read(name -> name.equals("reverse_chg_state") && modes[0]++>0 ? "2" : nodes.get(name))
   .state==ChargeStatus.State.UNKNOWN);
  nodes.remove("pen_soc");check(!ChargeStatus.read(nodes::get).charging());
  ChargeStatus removed=read("1","1","4","99",peer,"0");
  ChargeStatus waiting=read("0","1","0","255","255","0");
  ChargeStatus charging=read("0","1","4","99",peer,"0");
  ChargeStatus full=read("0","1","4","100",peer,"0");
  PenChargeSession session=new PenChargeSession();
  session.update(ChargeStatus.unknown());check(!session.hasAttachment());
  check(!session.shouldShow(ChargeStatus.unknown(),true));
  session.update(waiting);check(session.hasAttachment());
  check(!session.shouldShow(waiting,false));check(!session.shouldShow(waiting,true));
  session.update(charging);check(session.shouldShow(charging,true));
  session.markShown(charging);check(!session.shouldShow(charging,true));
  session.update(full);check(!session.shouldShow(full,true));
  session.update(removed);check(!session.hasAttachment());
  session.update(waiting);check(!session.shouldShow(waiting,true));
  session.update(charging);check(session.shouldShow(charging,true));
  session.markShown(charging);session.dismiss();
  session.update(full);check(!session.shouldShow(full,true));
  session.update(ChargeStatus.unknown());session.update(full);
  check(!session.shouldShow(full,true));
  session.update(removed);session.update(full);check(session.shouldShow(full,true));
  session.markShown(full);check(!session.shouldShow(full,true));
  ChargeAcquisition grace=new ChargeAcquisition();
  check(grace.update(ChargeStatus.unknown(),0).state==ChargeStatus.State.UNKNOWN);
  check(grace.update(removed,10).state==ChargeStatus.State.DETACHED);
  check(grace.update(waiting,100).state==ChargeStatus.State.ACQUIRING);
  check(grace.update(read("0","1","4","99",peer,"1"),600).state==ChargeStatus.State.ACQUIRING);
  check(grace.update(ChargeStatus.unknown(),1800).state==ChargeStatus.State.ACQUIRING);
  check(grace.update(waiting,3599).state==ChargeStatus.State.ACQUIRING);
  check(grace.update(waiting,3600).state==ChargeStatus.State.MISALIGNED);
  check(grace.update(charging,3700).charging());
  check(grace.update(full,3800).state==ChargeStatus.State.FULL);
  check(grace.update(removed,4000).state==ChargeStatus.State.DETACHED);
  check(grace.update(waiting,4100).state==ChargeStatus.State.ACQUIRING);
  check(grace.update(charging,4200).charging());
  check(grace.update(removed,4300).state==ChargeStatus.State.DETACHED);
  check(grace.update(ChargeStatus.unknown(),4400).state==ChargeStatus.State.UNKNOWN);
  ChargeStatus pending=grace.update(waiting,4500);
  check(pending.state==ChargeStatus.State.ACQUIRING && pending.level==-1 && pending.address==null);
  check(ChargeStatus.fromProvider(pending.state.name(),99,peer).state==ChargeStatus.State.ACQUIRING);
  PenChargeSession popup=new PenChargeSession();popup.update(pending);
  check(!popup.shouldShow(pending,true));
  ChargeStatus beforeDeadline=grace.update(waiting,7999);
  popup.update(beforeDeadline);check(!popup.shouldShow(beforeDeadline,true));
  ChargeStatus timeout=grace.update(waiting,8000);
  popup.update(timeout);check(timeout.state==ChargeStatus.State.MISALIGNED);
  check(!popup.shouldShow(timeout,false));check(popup.shouldShow(timeout,true));
  popup.markShown(timeout);check(!popup.shouldShow(timeout,true));
  popup.update(charging);check(popup.shouldShow(charging,true));
  popup.markShown(charging);check(!popup.shouldShow(charging,true));
  popup.dismiss();
  check(!popup.shouldShow(charging,true));
  popup.update(removed);popup.update(pending);check(!popup.shouldShow(pending,true));
  popup.update(full);check(popup.shouldShow(full,true));
  PenChargeSession inSettings=new PenChargeSession();
  inSettings.update(pending);inSettings.dismiss();
  inSettings.update(timeout);check(!inSettings.shouldShow(timeout,true));
  inSettings.update(charging);check(!inSettings.shouldShow(charging,true));
  inSettings.update(removed);inSettings.update(charging);check(inSettings.shouldShow(charging,true));
  System.out.println("Charge state assertions passed: "+checks);
 }
}
''')
jdk = Path(os.environ.get('SHENG_ROM_ROOT','/root/sheng-pixelos/android'))/'prebuilts/jdk/jdk21/linux-x86/bin'
commands = []
for argv in ([jdk/'javac','-encoding','UTF-8','-d',work/'classes',source,acquisition_source,session_source,test,
              source.with_name('PenDockPeer.java'), session_source.parents[5]/'tests/PenDockPeerTest.java'],
             [jdk/'java','-cp',work/'classes','org.lineageos.sheng.stylus.ChargeStateTest'],
             [jdk/'java','-cp',work/'classes','org.lineageos.sheng.stylus.PenDockPeerTest']):
    result = subprocess.run(list(map(str,argv)),capture_output=True,text=True)
    commands.append(dict(argv=list(map(str,argv)),exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr))
    if result.returncode: break
receipt = dict(passed=result.returncode==0,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
               dock_peer_source_sha256=hashlib.sha256(source.with_name('PenDockPeer.java').read_bytes()).hexdigest(),
               acquisition_source_sha256=hashlib.sha256(acquisition_source.read_bytes()).hexdigest(),
               session_source_sha256=hashlib.sha256(session_source.read_bytes()).hexdigest(),
               commands=commands,hardware_tested=False)
(work/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(work); print(result.stdout+result.stderr)
raise SystemExit(result.returncode)
