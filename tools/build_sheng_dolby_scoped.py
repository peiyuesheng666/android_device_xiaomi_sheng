#!/usr/bin/env python3
"""Build the complete owned Dolby APK using pinned existing platform headers.

This is a scoped javac/D8 build, NOT a full Soong/product rebuild. Do not reuse
the old product's source list: it predates DolbyTileService. Every current Java
source is compiled, and source/compiled manifest + real DEX definitions must
agree before the APK can be exported. Never installs or connects to a device.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile
import xml.etree.ElementTree as ET

from sheng_apk_components import verify_apk_components


def sha(path):
    with path.open('rb') as stream:
        digest=hashlib.sha256()
        for block in iter(lambda:stream.read(1048576),b''):digest.update(block)
        return digest.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom',type=Path,required=True)
    parser.add_argument('--platform-out',type=Path,required=True)
    parser.add_argument('--previous-apk',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    rom=args.rom.resolve(strict=True); platform=args.platform_out.resolve(strict=True)
    source=rom/'device/xiaomi/sheng/dolby/ShengDolby'
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    # Headers are exactly those declared by the normal current Soong javac
    # edge, from the existing populated platform build (not an edited jar).
    header_root=platform/'soong/.intermediates/frameworks/base/framework-minus-internal-res/android_common'
    headers=[header_root/'jarjar/turbine/framework-minus-internal-res.jar',
             header_root/'repackaged-jarjar/repackage-turbine/framework-minus-internal-res.0.jar']
    sdk=rom/'prebuilts/sdk/current/public/android.jar'
    jdk=rom/'prebuilts/jdk/jdk21/linux-x86'
    host=platform/'host/linux-x86'
    signer=rom/'prebuilts/sdk/tools/linux/lib/apksigner.jar'
    r8=rom/'prebuilts/r8/r8.jar'
    tools=[sdk,*headers,jdk/'bin/java',jdk/'bin/javac',host/'bin/aapt2',host/'bin/zipalign',signer,r8]
    inputs={str(p):sha(p) for p in tools}
    sources={str(p.relative_to(source)):sha(p) for p in sorted(source.rglob('*')) if p.is_file()}
    previous_sha=sha(args.previous_apk)
    env=dict(os.environ,LANG='C.UTF-8',LC_ALL='C.UTF-8',JAVA_HOME=str(jdk))
    commands=[]
    def run(argv,label):
        p=subprocess.run(list(map(str,argv)),cwd=rom,env=env,capture_output=True,timeout=300)
        (out/(label+'.stdout')).write_bytes(p.stdout);(out/(label+'.stderr')).write_bytes(p.stderr)
        commands.append(dict(label=label,argv=list(map(str,argv)),returncode=p.returncode))
        (out/'commands.json').write_text(json.dumps(commands,indent=2))
        p.check_returncode();return (p.stdout+p.stderr).decode(errors='replace')
    for name in ('generated','classes','dex'):(out/name).mkdir()
    run([host/'bin/aapt2','compile','--dir',source/'res','-o',out/'resources.zip'],'aapt-compile')
    run([host/'bin/aapt2','link','-I',sdk,'--manifest',source/'AndroidManifest.xml',
         '--min-sdk-version','1','--target-sdk-version','37','--java',out/'generated',
         '-o',out/'resources.apk',out/'resources.zip'],'aapt-link')
    java_sources=sorted((source/'src').rglob('*.java'))+sorted((out/'generated').rglob('*.java'))
    assert any(p.name=='DolbyTileService.java' for p in java_sources)
    run([jdk/'bin/javac','-source','8','-target','8','-encoding','UTF-8',
         '-classpath',':'.join(map(str,[*headers,sdk])),'-d',out/'classes',*java_sources],'javac-all-owned-sources')
    jar=out/'classes.jar'
    with zipfile.ZipFile(jar,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted((out/'classes').rglob('*.class')):z.write(p,p.relative_to(out/'classes').as_posix())
    run([jdk/'bin/java','-cp',r8,'com.android.tools.r8.D8','--release','--min-api','1',
         '--lib',sdk,'--output',out/'dex',jar],'d8')
    unsigned=out/'ShengDolby.unsigned.apk'
    with zipfile.ZipFile(out/'resources.apk') as res,zipfile.ZipFile(unsigned,'w',zipfile.ZIP_DEFLATED) as z:
        for entry in res.infolist():z.writestr(entry,res.read(entry))
        for p in sorted((out/'dex').glob('*.dex')):
            assert p.read_bytes()[:8]==b'dex\n035\0'
            z.write(p,p.name)
    aligned=out/'ShengDolby.aligned.apk';apk=out/'ShengDolby.apk'
    run([host/'bin/zipalign','-P','16','-f','4',unsigned,aligned],'zipalign')
    security=rom/'build/target/product/security'
    run([jdk/'bin/java','-jar',signer,'sign','--key',security/'platform.pk8',
         '--cert',security/'platform.x509.pem','--min-sdk-version','1',
         '--v1-signing-enabled','true','--v2-signing-enabled','true','--v3-signing-enabled','true',
         '--out',apk,aligned],'platform-sign')
    signature=run([jdk/'bin/java','-jar',signer,'verify','--verbose','--print-certs','--min-sdk-version','1',apk],'verify-signature')
    old_signature=run([jdk/'bin/java','-jar',signer,'verify','--print-certs','--min-sdk-version','1',args.previous_apk],'verify-old-signature')
    certificate=lambda text:re.search(r'certificate SHA-256 digest: ([0-9a-f]+)',text)[1]
    assert certificate(signature)==certificate(old_signature)
    assert 'Verified using v1 scheme (JAR signing): true' in signature
    run([host/'bin/zipalign','-c','-P','16','4',apk],'verify-zipalign')
    manifest=run([host/'bin/aapt2','dump','xmltree',apk,'--file','AndroidManifest.xml'],'compiled-manifest')
    components=verify_apk_components(apk,manifest,(source/'AndroidManifest.xml').read_text())
    assert 'org.lineageos.sheng.dolby.DolbyTileService' in components['manifest_components']
    badging=run([host/'bin/aapt2','dump','badging',apk],'badging')
    root=ET.fromstring((source/'AndroidManifest.xml').read_text()); ns='{http://schemas.android.com/apk/res/android}'
    version=root.attrib[ns+'versionCode'];version_name=root.attrib[ns+'versionName']
    assert f"versionCode='{version}' versionName='{version_name}'" in badging
    assert 'android.intent.category.LAUNCHER' not in manifest
    assert sources=={str(p.relative_to(source)):sha(p) for p in sorted(source.rglob('*')) if p.is_file()}
    assert inputs=={str(p):sha(p) for p in tools} and sha(args.previous_apk)==previous_sha
    receipt=dict(passed=True,scope='complete owned app scoped javac/D8 build; not a normal Soong/product rebuild',
        apk=str(apk),apk_sha256=sha(apk),apk_bytes=apk.stat().st_size,version_code=int(version),version_name=version_name,
        components=components,source_files_sha256=sources,tool_and_header_sha256=inputs,
        previous_apk_sha256=previous_sha,platform_certificate_sha256=certificate(signature),
        all_current_java_sources_compiled=True,v1_signature_verified=True,zipalign_16k_verified=True,
        normal_soong_build=False,full_product_build=False,installed=False,runtime_verified=False)
    (out/'qualification.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k not in ('source_files_sha256','tool_and_header_sha256')},indent=2))


if __name__=='__main__':main()
