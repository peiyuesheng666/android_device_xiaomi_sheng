#!/usr/bin/env python3
"""Replace the pen APKs in an installed product application layout."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import time
from package_sheng_batch_helpers import certificates, merge_parent, publish_batch, sha, stage_ext4
from package_sheng_model_followup import ROM, HOST, run

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=None)
    parser.add_argument('--baseline',type=Path,required=True,help='Exact currently installed package manifest')
    parser.add_argument('--include-ime',action='store_true',
                        help='Include the separately qualified OEM IME; pen updates otherwise contain only the two pen APKs')
    args=parser.parse_args()
    workspace=Path(__file__).resolve().parents[4];device=workspace/'device/xiaomi/sheng'
    build_path=args.build.resolve();build=json.loads(build_path.read_text())
    assert build['passed'] and build['native_service_unchanged'] and build['policy_unchanged']
    controls=build.get('controls_regression_passed') is True
    built_ime=build.get('preinstalled_ime_included',build.get('ime_original_signature_preserved') is True)
    if args.include_ime:assert built_ime and build.get('ime_original_signature_preserved') is True
    assert not build['normal_module_build_passed'] and not build['ninja_graph_loaded']
    native_path=workspace/'artifacts/system-hardware-followup-sheng-r65/build-result.json'
    assert sha(native_path)==build['baseline_manifest_sha256']
    previous_path=args.baseline.absolute()
    previous=json.loads(previous_path.read_text())
    assert previous['kind'] in ('product-app-layout','product-pen-ui','codec2-service-update',
                                'vendor-runtime-update')
    assert previous['complete_avb_chain_verified']
    assert previous.get('stylus_native_service_unchanged',previous['native_service_unchanged'])
    def check_source():
        for relative,digest in build['source_sha256'].items():assert sha(device/relative)==digest,relative
        if 'product_registration_sha256' in build:
            assert sha(device/'device.mk')==build['product_registration_sha256']
        assert sha(build_path)==build_hash
    build_hash=sha(build_path);check_source()
    baseline=previous['files']+previous['unchanged_partition_files']
    assert len(baseline)==14 and len({row['partition'] for row in baseline})==14
    chain={row['partition']:Path(previous['work_dir'])/'complete-chain'/row['name'] for row in baseline}
    for row in baseline:
        path=chain[row['partition']]
        assert path.stat().st_size==row['bytes'] and sha(path)==row['sha256'],path
    product=Path(build['product_root']);entries={}
    expected={'product/app/ShengPenSettings/ShengPenSettings.apk','product/priv-app/ShengStylus/ShengStylus.apk'}
    if built_ime:
        assert build['ime_original_signature_preserved'] is True
        expected.add('product/app/ShengSogouIme/ShengSogouIme.apk')
    assert set(build['apk_files'])==expected
    for relative,record in build['apk_files'].items():
        path=product/relative
        assert path.stat().st_size==record['bytes'] and sha(path)==record['sha256']
        if relative!='product/app/ShengSogouIme/ShengSogouIme.apk' or args.include_ime:
            entries[relative.removeprefix('product/')]=dict(source=str(path),bytes=record['bytes'],sha256=record['sha256'])
    work=args.work.resolve();work.mkdir(parents=True,exist_ok=False)
    assert work.stat().st_dev==Path('/').stat().st_dev
    assert shutil.disk_usage(work).free>8*1024**3
    run(['python3',device/'tools/prepare_sheng_stylus_swap.py','--work',work],capture_output=True)
    sys.path.insert(0,str(ROM/'external/avb'));import avbtool
    avb=avbtool.Avb()
    print('Packaging the declared pen APKs in product; verifying signatures and filesystem metadata.',flush=True)
    image,descriptor,stage=stage_ext4('product',chain['product'],entries,{},work,avb,avbtool,
        certificates(product/'product/priv-app/ShengStylus/ShengStylus.apk'),
        replacement_mtimes={relative:int(time.time()) for relative in entries
                            if relative!='app/ShengSogouIme/ShengSogouIme.apk'},
        source_product=product)
    assert stage['metadata_preserved']
    outputs={'product':image,'vbmeta_system':work/'vbmeta_system.img'}
    merge_parent(avb,avbtool,chain['vbmeta_system'],[descriptor],outputs['vbmeta_system'],'SHA256_RSA2048',work)
    complete=work/'complete-chain';complete.mkdir()
    for part,path in chain.items():(complete/(part+'.img')).symlink_to(outputs.get(part,path).resolve())
    verification=run([HOST/'avbtool','verify_image','--image',complete/'vbmeta.img','--follow_chain_partitions'],capture_output=True,text=True)
    (work/'avb-verification.log').write_text(verification.stdout+verification.stderr)
    check_source()
    report=dict(kind='product-pen-ui',date_utc=datetime.now(timezone.utc).isoformat(),
        baseline_manifest=previous_path.relative_to(workspace).as_posix(),
        native_manifest_sha256=sha(native_path),applications=previous['applications'],
        baseline_manifest_sha256=sha(previous_path),baseline_partitions=baseline,
        unchanged_partition_files=[row for row in baseline if row['partition'] not in outputs],
        entries={'product':entries},partition_reports={'product':stage},work_dir=str(work),
        partition_sizes_unchanged=True,removals={},
        build_receipt=build_path.relative_to(workspace).as_posix(),build_receipt_sha256=build_hash,
        source_sha256=build['source_sha256'],complete_avb_chain_verified=True,
        policy_and_vintf_inputs_unchanged=True,native_service_unchanged=True,
        systemui_unchanged=True,normal_module_build_passed=False,targeted_ui_build_passed=True,
        installed=False,e_drive_swap_allowed=False,native_c_staging=True,
        preinstalled_ime_included=True,ime_updated=args.include_ime,built_ime_deferred=bool(built_ime and not args.include_ime))
    report['stylus_native_service_unchanged']=True
    for key in ('scoped_file_contexts','scoped_file_contexts_sha256'):
        if key in previous:report[key]=previous[key]
    if controls:
        report.update(targeted_controls_build_passed=True,
                      controls_validation_sha256=build['controls_validation_sha256'])
    if 'product_registration_sha256' in build:
        report['product_registration_sha256']=build['product_registration_sha256']
    if args.include_ime:report['ime_original_signature_preserved']=True
    destination=args.output.resolve() if args.output else workspace/'artifacts/system-hardware-followup-sheng-product-pen-ui'
    publish_batch(destination,outputs,report)
    print(destination/'build-result.json',flush=True)

if __name__=='__main__':main()
