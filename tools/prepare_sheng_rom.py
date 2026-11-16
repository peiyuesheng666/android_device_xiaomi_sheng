#!/usr/bin/env python3
"""Install sheng inputs and apply the small, pinned ROM patch set."""
from pathlib import Path
import argparse, hashlib, json, os, shutil, subprocess, sys

def sha(p):
    with p.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    if sys.version_info < (3,11): raise SystemExit('Python 3.11 or newer is required')
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--rom',type=Path,required=True)
    ap.add_argument('--kernel-deps',type=Path,required=True)
    ap.add_argument('--check',action='store_true',help='Read-only input and patch preflight')
    args=ap.parse_args()
    package=Path(__file__).resolve().parents[1]
    rom=args.rom.resolve(); deps=args.kernel_deps.resolve()
    required=['build/envsetup.sh','vendor/lineage/config/common_full_tablet_wifionly.mk',
      'hardware/qcom-caf/common/common.mk','hardware/qcom-caf/sm8550/audio/primary-hal/Android.bp',
      'hardware/qcom-caf/sm8550/display/Android.bp','device/qcom/sepolicy_vndr/SEPolicy.mk',
      'vendor/qcom/opensource/power/config/kalama/powerhint.xml',
      'vendor/qcom/opensource/commonsys-intf/display/Android.bp','tools/extract-utils']
    for n in required:
        if not (rom/n).exists(): raise SystemExit('Missing ROM dependency: '+n)
    for n in ['prebuilts/clang/host/linux-x86/clang-r584948c/bin/clang',
      'prebuilts/rust-toolchain/linux-x86/1.91.1.p3/bin/rustc',
      'prebuilts/clang-tools/linux-x86/bin/bindgen',
      'prebuilts/kernel-build-tools/linux_musl-x86/bin/pahole',
      'prebuilts/build-tools/linux-x86/bin/make',
      'elfutils-0.193/include/elfutils/libdw.h','elfutils-0.193/lib/libelf.so']:
        if not (deps/n).exists(): raise SystemExit('Missing kernel build dependency: '+str(deps/n))
    dep_link=rom.parent/'diagnostics/kernel618-android-deps'
    if (dep_link.exists() or dep_link.is_symlink()) and dep_link.resolve()!=deps:
        raise SystemExit('Existing kernel dependency path points elsewhere: '+str(dep_link))
    for n in ('kernel/xiaomi/sheng-build/sources/k618/ws/common/Makefile','vendor/xiaomi/sheng/sheng-vendor.mk'):
        if not (rom/n).is_file(): raise SystemExit('Missing cloned source or LFS payload: '+n)
    series=json.loads((package/'patches/series.json').read_text())
    pending=[]
    for item in series:
        repo=rom/item['project']; patch=package/'patches'/item['patch']
        if all((repo/f['path']).is_file() and sha(repo/f['path'])==f['after_sha256'] for f in item['files']):
            print('Already applied:',item['patch']); continue
        if not all((repo/f['path']).is_file() and sha(repo/f['path'])==f['before_sha256'] for f in item['files']):
            raise SystemExit('Source differs from patch baseline: '+item['project']+
                '; use the matching manifest or rebase this patch explicitly')
        subprocess.run(['git','apply','--check',str(patch)],cwd=repo,check=True)
        pending.append((repo,patch))
    subprocess.run([sys.executable,package/'tools/prepare_sheng_face_engine.py',
                    '--verify-only'],check=True)
    if args.check:
        print('Preflight passed. No ROM files were changed.'); return
    subprocess.run(['rsync','-a',str(package/'prebuilts')+'/',str(rom/'device/xiaomi/sheng-kernel')+'/'],check=True)
    link=rom/'kernel/xiaomi/sheng'
    expected=(rom/'kernel/xiaomi/sheng-build/sources/k618/ws/common').resolve()
    if link.exists() or link.is_symlink():
        if link.resolve()!=expected: raise SystemExit('Existing kernel/xiaomi/sheng points elsewhere')
    else: link.symlink_to('sheng-build/sources/k618/ws/common')
    dep_link.parent.mkdir(parents=True,exist_ok=True)
    if not dep_link.exists(): dep_link.symlink_to(deps,target_is_directory=True)
    for repo,patch in pending: subprocess.run(['git','apply',str(patch)],cwd=repo,check=True)
    for item in series:
        assert all(sha(rom/item['project']/f['path'])==f['after_sha256'] for f in item['files'])
    assert (rom/'kernel/xiaomi/sheng').resolve()==(rom/'kernel/xiaomi/sheng-build/sources/k618/ws/common').resolve()
    print('Ready. Follow BUILD.md to select the ROM product and compile.')

if __name__=='__main__': main()
