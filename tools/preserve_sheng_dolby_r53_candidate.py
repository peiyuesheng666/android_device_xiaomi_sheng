#!/usr/bin/env python3
"""Save only this turn's uninstalled Dolby changes and restore its r52 source baseline."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    device = Path(__file__).resolve().parents[1]
    workspace = device.parents[2]
    mirror = Path('/root/sheng-lineage/lineage-24.0/device/xiaomi/sheng')
    relative = 'dolby/ShengDolby'
    names = ['AndroidManifest.xml',
             'src/org/lineageos/sheng/dolby/AtmosApplication.java',
             'src/org/lineageos/sheng/dolby/AtmosActivity.java',
             'src/org/lineageos/sheng/dolby/ParameterEdits.java']
    saved = device/'docs/candidates/dolby-r53/source'
    saved.mkdir(parents=True, exist_ok=False)
    receipt = {'installed_revision': 52, 'candidate_installed': False, 'sources': {}}
    for name in names:
        source, output = device/relative/name, saved/name
        assert digest(source) == digest(mirror/relative/name), 'Mirror changed: '+name
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, output)
        receipt['sources'][name] = digest(output)
    for name in names:
        source, output, build_source = device/relative/name, saved/name, mirror/relative/name
        assert digest(source) == digest(build_source) == digest(output)
        if name.endswith('ParameterEdits.java'):
            assert not subprocess.check_output(['git','-C',str(workspace),'ls-files','--',
                'device/xiaomi/sheng/'+relative+'/'+name]).strip()
            source.unlink()
            build_source.unlink()
        else:
            original = subprocess.check_output(['git','-C',str(workspace),'show',
                'HEAD:device/xiaomi/sheng/'+relative+'/'+name])
            source.write_bytes(original)
            build_source.write_bytes(original)
    assert 'versionCode="51"' in (device/relative/'AndroidManifest.xml').read_text()
    subprocess.run(['git','-C',str(workspace),'diff','--exit-code','--',
                    'device/xiaomi/sheng/'+relative],check=True)
    (saved.parent/'preservation.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('Preserved r53 candidate; Windows and WSL product sources restored to installed r52 baseline')


if __name__ == '__main__':
    main()
