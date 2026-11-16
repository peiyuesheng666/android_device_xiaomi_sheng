#!/usr/bin/env python3
"""Stage the reviewed face engine for Soong; no unpinned binary or model is accepted."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy(source, target):
    if not target.is_file() or sha(source) != sha(target):
        shutil.copyfile(source, target)


def verify_staged(feature, target, manifest, inventory):
    expected = {'opencv-4.13.0.aar': inventory['files_sha256']['opencv-4.13.0.aar'],
                'assets/licenses/engine-dependencies.json': sha(manifest),
                'assets/licenses/FaceUnlock-LICENSE': sha(feature / 'LICENSE')}
    expected.update(('assets/models/' + name, inventory['files_sha256'][name])
                    for name in inventory['models'])
    expected.update(('assets/' + name, digest)
                    for name, digest in inventory['license_files_sha256'].items())
    expected.update(('assets/licenses/' + name, inventory['files_sha256'][name])
                    for name in inventory['additional_notices'])
    files = {path.relative_to(target).as_posix(): sha(path)
             for path in target.rglob('*') if path.is_file()}
    if files != expected:
        raise ValueError('Staged face engine files do not match their pinned inputs')
    with zipfile.ZipFile(target / 'opencv-4.13.0.aar') as archive:
        for name, digest in {
            'classes.jar': inventory['files_sha256']['opencv-classes.jar'],
            'jni/arm64-v8a/libopencv_java4.so': inventory['files_sha256']['libopencv_java4.so'],
            'jni/arm64-v8a/libc++_shared.so': inventory['libcxx_shared_sha256'],
        }.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise ValueError('Staged OpenCV member differs: ' + name)
    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--device', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--engine-dir', type=Path)
    parser.add_argument('--verify-only', action='store_true',
                        help='Verify the preserved staged payload without requiring download archives')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    feature = args.device / 'interfaces/biometrics/softwareface'
    manifest = feature / 'engine-dependencies.json'
    inventory = json.loads(manifest.read_text())
    target = args.device / 'interfaces/biometrics/systemface/cache/engine'
    if args.verify_only:
        if args.engine_dir:
            parser.error('--verify-only does not accept --engine-dir')
        files = verify_staged(feature, target, manifest, inventory)
        receipt = {'staging_passed': True, 'verification_only': True,
                   'dependency_manifest_sha256': sha(manifest),
                   'staged_dir': str(target), 'files_sha256': files}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps({'staging_passed': True, 'staged_files': len(files)}))
        return
    if not args.engine_dir:
        parser.error('Specify --engine-dir to stage inputs, or --verify-only to check them')
    source = args.engine_dir.resolve()
    for name, expected in inventory['files_sha256'].items():
        if sha(source / name) != expected:
            raise ValueError(f'Unreviewed engine input: {name}')
    for name, expected in inventory['license_files_sha256'].items():
        if sha(feature / name) != expected:
            raise ValueError(f'Missing or changed license: {name}')
    with zipfile.ZipFile(source / 'opencv-4.13.0.aar') as archive:
        assert hashlib.sha256(archive.read('jni/arm64-v8a/libc++_shared.so')).hexdigest() == inventory['libcxx_shared_sha256']
        assert archive.read('classes.jar') == (source / 'opencv-classes.jar').read_bytes()
        assert archive.read('jni/arm64-v8a/libopencv_java4.so') == (source / 'libopencv_java4.so').read_bytes()
    target.mkdir(parents=True, exist_ok=True)
    copy(source / 'opencv-4.13.0.aar', target / 'opencv-4.13.0.aar')
    assets = target / 'assets'
    (assets / 'models').mkdir(parents=True, exist_ok=True)
    (assets / 'licenses').mkdir(parents=True, exist_ok=True)
    for name in inventory['models']:
        copy(source / name, assets / 'models' / name)
    for name in inventory['license_files_sha256']:
        copy(feature / name, assets / name)
    for name in inventory['additional_notices']:
        copy(source / name, assets / 'licenses' / name)
    copy(manifest, assets / 'licenses/engine-dependencies.json')
    copy(feature / 'LICENSE', assets / 'licenses/FaceUnlock-LICENSE')
    files = verify_staged(feature, target, manifest, inventory)
    receipt = {'staging_passed': True, 'dependency_manifest_sha256': sha(manifest),
               'engine_dir': str(source), 'staged_dir': str(target), 'files_sha256': files}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'staging_passed': True, 'staged_files': len(files)}))


if __name__ == '__main__':
    main()
