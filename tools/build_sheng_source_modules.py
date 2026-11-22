#!/usr/bin/env python3
"""Compile and install the source kernel's Qualcomm and tablet modules."""
from pathlib import Path
import argparse, hashlib, json, os, shutil, subprocess, sys

assert sys.version_info >= (3, 11), 'Use the Android tree prebuilt Python (3.11 or newer)'

parser=argparse.ArgumentParser()
parser.add_argument('--kernel-out',type=Path,required=True)
parser.add_argument('--install-root',type=Path)
args=parser.parse_args()
core=args.kernel_out.resolve()
tools=Path(__file__).resolve().parent
kernel_overlays=tools.parent/'interfaces/kernel/6.18'
rom=tools.parents[3]
source_project=rom/'kernel/xiaomi/sheng-build'
deps=rom.parent/'diagnostics/kernel618-android-deps'
b=core.parent/'SHENG_VENDOR_KERNEL_OBJ'
project=core.parent/'SHENG_KERNEL_PROJECT'
sha=lambda p:hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
env=dict(os.environ,BUILD_ROOT=str(b),PREBUILTS=str(deps/'prebuilts'),
         ELFUTILS=str(deps/'elfutils-0.193'),PYTHON=sys.executable,JOBS='4',
         SHENG_BUILD_MODE='release',TAG='android-source-build')
# The standalone driver project establishes this tool environment itself, but
# its project bootstrap runs before build-env.sh. Use the same pinned tools
# from the start, including host identity tools needed by project-env.sh.
env['PATH']=':'.join(str(deps/'prebuilts'/part) for part in (
    'clang/host/linux-x86/clang-r584948c/bin',
    'rust-toolchain/linux-x86/1.91.1.p3/bin',
    'clang-tools/linux-x86/bin','kernel-build-tools/linux_musl-x86/bin',
    'build-tools/linux-x86/bin'))+':/usr/sbin:/usr/bin:/sbin:/bin'
env.pop('K618_LIMITS_VERIFIED',None)
env.pop('MAKEFLAGS',None)
def run(argv):
    subprocess.run(list(map(str,argv)),cwd=rom,env=env,check=True)
if args.install_root is None:
    # A WSL virtual disk can report plenty of guest space even with a full C:.
    # Fail before copying sources or compiling if the backing host is too low.
    host_c = Path('/mnt/c')
    if host_c.is_mount() and 'microsoft' in os.uname().release.lower():
        free_gib = shutil.disk_usage(host_c).free / (1 << 30)
        if free_gib < 12:
            parser.exit(1, f'Windows C: only has {free_gib:.2f} GiB free; reclaim space before this build (minimum 12 GiB).\n')
    # Standalone driver scripts create logs, provenance and dist files below
    # their project. Run a writable copy under OUT_DIR, keeping source inputs RO.
    project.mkdir(parents=True,exist_ok=True)
    for name in ('android','kernel','patches','profiles','provenance','scripts','tools','validation'):
        shutil.copytree(source_project/name,project/name,symlinks=True,dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__'))
    for source in list(source_project.glob('*.sh')) + [source_project/name for name in
            ('SOURCE-SHA256.json','SOURCE.json','sheng_defconfig')]:
        shutil.copy2(source,project/source.name)
    sources=project/'sources'
    if not sources.exists():
        sources.symlink_to(source_project/'sources',target_is_directory=True)
    assert sources.is_symlink() and sources.resolve()==(source_project/'sources').resolve()
    for patch in sorted((kernel_overlays/'android-module-patches').glob('*.patch')):
        subprocess.run(['git','apply','--check',str(patch)],cwd=project,env=env,check=True)
        subprocess.run(['git','apply',str(patch)],cwd=project,env=env,check=True)
    run(['bash',project/'scripts/prepare.sh'])
    # Clean R2 inputs can predate the keyboard state/recovery overlays.
    # Later patches edit their headers; the final source contract pins the files.
    keyboard = b/'k618/sheng-ports/keyboard'
    for header, name in (
            ('sheng_nanosic_state.h', '0036-keyboard-cached-connection-state.patch'),
            ('sheng_nanosic_recovery.h', '0037-keyboard-timeout-firmware-recovery.patch')):
        if not (keyboard/header).is_file():
            patch = kernel_overlays/'patches'/name
            subprocess.run(['git','apply','--check',str(patch)],cwd=b,env=env,check=True)
            subprocess.run(['git','apply',str(patch)],cwd=b,env=env,check=True)
    for name in ("0038-keyboard-panel-state.patch", "0039-keyboard-boot-readiness.patch",
                 "0040-keyboard-sleep-caps.patch"):
        patch = kernel_overlays/'patches'/name
        applied = subprocess.run(['git','apply','--reverse','--check',str(patch)],
                                 cwd=b,env=env,capture_output=True).returncode == 0
        if not applied:
            subprocess.run(['git','apply','--check',str(patch)],cwd=b,env=env,check=True)
            subprocess.run(['git','apply',str(patch)],cwd=b,env=env,check=True)
    run([sys.executable, tools/'prepare_sheng_dp_usb.py', '--source-root', b/'k618'])
    run([sys.executable, tools/'prepare_sheng_charge_error_contract.py', '--source-root', b/'k618'])
    run([sys.executable, tools/'prepare_sheng_wlan_response.py', '--source-root', b/'k618'])
    out=b/'k618/out-gki'
    if not out.exists():
        out.symlink_to(core,target_is_directory=True)
    assert out.resolve()==core
    shutil.copy2(core/'.config',core/'kernel.config')
    shutil.copy2(core/'arch/arm64/boot/Image',core/'kernel-Image')
    ready=dict(defconfig_sha256=sha(project/'sheng_defconfig'),
               kernel_config_sha256=sha(core/'kernel.config'),kernel_image_sha256=sha(core/'kernel-Image'),
               walt_source_receipt_sha256=sha(project/'provenance/walt-compatibility.json'))
    (core/'.kernel-ready.json').write_text(json.dumps(ready,indent=2)+'\n')
    run(['bash',project/'buildmodules.sh'])
    # `make modules` can relink vmlinux. Its split-BTF base and all modules
    # now refer to that final link, not the Image copied before this stage.
    # Derive Image again, preserving the superseded bytes/receipt as evidence.
    import time
    run([sys.executable, tools/'sheng_kernel_image.py', '--kernel-out', core,
         '--objcopy', shutil.which('llvm-objcopy', path=env['PATH']), '--finalize',
         '--evidence', b/('image-finalization-'+str(time.time_ns()))])
    # Qualification and OTA preparation require fresh generated directories.
    # Regenerate them after successful module compilation on incremental builds.
    for name in ('qualified','android-modules'):
        generated=b/name
        assert generated.parent==b and not generated.is_symlink()
        if generated.exists():
            shutil.rmtree(generated)
    run(['bash',project/'verify.sh'])
    run([sys.executable,tools/'prepare_source_kernel_ota.py',
         '--build-root',b,'--project',project,'--output',b/'android-modules'])
else:
    run([sys.executable, tools/'sheng_kernel_image.py', '--kernel-out', core,
         '--objcopy', shutil.which('llvm-objcopy', path=env['PATH'])])
    validation=json.loads((b/'qualified/verification.json').read_text())
    assert validation['passed']
    release=(core/'include/config/kernel.release').read_text().strip()
    destination=args.install_root.resolve()/'lib/modules'/release
    assert destination.is_relative_to(args.install_root.resolve())
    destination.mkdir(parents=True,exist_ok=True)
    # Replace this invocation's generic modules with the qualified provider set.
    # The collection policy explicitly selects each core/SoC duplicate provider.
    for path in destination.rglob('*.ko'):
        assert path.resolve().is_relative_to(destination.resolve())
        path.unlink()
    target=destination/'kernel'
    target.mkdir(exist_ok=True)
    for source in sorted((b/'android-modules/modules').glob('*.ko')):
        shutil.copy2(source,target/source.name)
    shutil.copy2(b/'android-modules/module-plan.json',destination/'sheng-module-plan.json')
    print('Installed the qualified source-built modules for Android packaging.',flush=True)
