#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Offline Windows end-to-end test; the fake ADB never contacts a device."""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

kit = Path(__file__).resolve().parent
workspace = kit.parents[4]
out = workspace / 'reports' / ('usb-log-kit-test-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
stage = out / 'kit with spaces'
(stage / 'platform-tools').mkdir(parents=True)
for name in ('Capture-Usb.ps1', 'capture-state.sh'):
    shutil.copyfile(kit / name, stage / name)
source = out / 'FakeAdb.cs'
source.write_text(r'''
using System;
using System.IO;
using System.Threading;
class FakeAdb {
    static int Main(string[] args) {
        File.AppendAllText(Environment.GetEnvironmentVariable("FAKE_ADB_ARGS"), string.Join("\t", args) + "\n");
        if (args[0] == "devices") { Console.WriteLine("List of devices attached\nFAKE123\tdevice product:sheng model:Test"); return 0; }
        if (args[0] != "-s" || args[1] != "FAKE123") return 81;
        if (args[2] == "push") { Console.WriteLine("1 file pushed"); return 0; }
        if (args[2] != "shell" || args.Length != 4) return 82;
        string cmd = args[3];
        if (cmd == "getprop ro.serialno") {
            string file = Environment.GetEnvironmentVariable("FAKE_ADB_COUNT");
            int count = File.Exists(file) ? int.Parse(File.ReadAllText(file)) : 0;
            File.WriteAllText(file, (count + 1).ToString());
            if (count == 0) { Console.Error.WriteLine("device offline"); return 1; }
            Console.WriteLine("FAKE123"); return 0;
        }
        if (cmd.StartsWith("getprop ro.serialno;")) { Console.WriteLine("FAKE123\nsheng\nTest/ROM\nuid=2000(shell)"); return 0; }
        if (cmd == "su -c 'id'") {
            if (Environment.GetEnvironmentVariable("FAKE_SU_MISSING") == "1") { Console.Error.WriteLine("su: inaccessible or not found"); return 127; }
            Console.WriteLine("uid=0(root)"); return 0;
        }
        if (cmd.Contains("logcat -b all")) { Console.WriteLine("TEST USB link event"); Thread.Sleep(1500); return 0; }
        if (cmd.Contains("dmesg")) { Console.Error.WriteLine("dmesg: Permission denied (fixture)"); return 1; }
        if (cmd.Contains("sh /data/local/tmp/")) { Console.WriteLine("FILE: /sys/class/udc/test/current_speed\nhigh-speed\nFILE: maximum_speed\nsuper-speed"); return 0; }
        Console.WriteLine("fixture output"); return 0;
    }
}
''', encoding='utf-8')
compiler = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
subprocess.run([str(compiler), '/nologo', '/out:' + str(stage/'platform-tools/adb.exe'), str(source)], check=True)
env = os.environ.copy()
env['FAKE_ADB_ARGS'] = str(out/'argv.txt')
env['FAKE_ADB_COUNT'] = str(out/'count.txt')
missing_su = os.environ.get('FAKE_SU_MISSING') == '1'
run = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
    str(stage/'Capture-Usb.ps1'), '-Seconds', '15', '-NoPause', '-UseSu'],
    capture_output=True, env=env, timeout=120)
(out/'run.stdout.txt').write_bytes(run.stdout)
(out/'run.stderr.txt').write_bytes(run.stderr)
assert run.returncode == 0, run.stderr.decode(errors='replace')
archives = list((stage/'logs').glob('*.zip'))
assert len(archives) == 1
with zipfile.ZipFile(archives[0]) as archive:
    assert archive.testzip() is None
    def read(name):
        return archive.read(next(n for n in archive.namelist() if n.endswith('/'+name))).decode('utf-8-sig')
    manifest = json.loads(read('manifest.json'))
    events = json.loads(read('events.json'))
    commands = json.loads(read('commands.json'))
    assert manifest['hardwareSerial'] == 'FAKE123' and manifest['suRequested']
    assert any('disconnected' in e['message'] for e in events)
    assert any('restored' in e['message'] for e in events)
    assert 'Permission denied' in read('kernel-before.txt')
    assert 'high-speed' in read('after-state.txt')
    assert any(c.get('exitCode') == 1 for c in commands)
    assert 'capture-error.txt' not in [Path(n).name for n in archive.namelist()]
argv = (out/'argv.txt').read_text()
assert ("su -c 'dmesg -w'" in argv) == (not missing_su)
assert manifest['suActive'] == (not missing_su)
assert any(c['name'] == 'kernel-logcat-before' for c in commands)
if missing_su:
    assert any('su unavailable' in e['message'] for e in events)
assert 'logcat -b all -v threadtime -T 1' in argv
assert 'rm -f /data/local/tmp/sheng-usb-capture-' in argv
(out/'result.json').write_text(json.dumps({'passed': True, 'coverage': [
    'PowerShell 5.1 execution', 'paths with spaces and Unicode', 'ADB argv and su quoting',
    'disconnect and recovery', 'permission denial retained', 'stream restart',
    'snapshots and final cleanup', 'ZIP integrity and receipts'], 'archive': str(archives[0])}, indent=2))
print(out)
