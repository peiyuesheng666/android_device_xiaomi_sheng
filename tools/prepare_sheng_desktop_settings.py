#!/usr/bin/env python3
"""Stage device-owned native Settings page; no separate app or launcher entry."""
import argparse
import hashlib
import json
from pathlib import Path


def prepare(rom, source):
    settings = rom / 'packages/apps/Settings'
    gateway = settings / 'src/com/android/settings/core/gateway/SettingsGateway.java'
    text = gateway.read_text()
    entry = '        "com.android.settings.sheng.DesktopModeSettings",\n'
    anchor = '    public static final String[] ENTRY_FRAGMENTS = {\n'
    assert text.count(anchor) == 1, 'Settings fragment allowlist changed'
    assert text.count(entry) <= 1, 'Duplicate desktop fragment allowlist entry'
    homepage = settings / 'src/com/android/settings/homepage/TopLevelSettings.java'
    homepage_text = homepage.read_text()
    icon_anchor = 'getHelper().setIconVisible(isRegularLayout);'
    icon_choice = ('getHelper().setIconVisible(isRegularLayout\n'
                   '                        || "sheng".equals(android.os.Build.DEVICE));')
    assert (homepage_text.count(icon_anchor) == 1 or homepage_text.count(icon_choice) == 1), \
        'Settings homepage split layout changed'
    manifest = settings / 'AndroidManifest.xml'
    manifest_text = manifest.read_text()
    service = (source / 'interfaces/display/desktop/qs-service.xml').read_text()
    assert manifest_text.count('    </application>') == 1, 'Settings application changed'
    service_name = 'com.android.settings.sheng.DesktopModeSettings$DesktopTileService'
    assert manifest_text.count(service_name) <= 1, 'Duplicate desktop tile'
    long_press = settings / 'src/com/android/settings/qstile/QSTileLongPressGatewayActivity.kt'
    long_press_text = long_press.read_text()
    anchor_when = '        when (tileComponent?.className) {\n'
    assert long_press_text.count(anchor_when) == 1, 'Settings tile gateway changed'
    route = '''            com.android.settings.sheng.DesktopModeSettings.DesktopTileService::class.java.name -> {
                SubSettingLauncher(this)
                    .setDestination(com.android.settings.sheng.DesktopModeSettings::class.java.name)
                    .setSourceMetricsCategory(SettingsEnums.SETTINGS_SYSTEM_CATEGORY)
                    .launch()
                finish()
                return
            }
'''
    files = []
    for part in ('src', 'res'):
        for original in (source / 'interfaces/display/desktop' / part).rglob('*'):
            if not original.is_file():
                continue
            target = settings / part / original.relative_to(source / 'interfaces/display/desktop' / part)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or target.read_bytes() != original.read_bytes():
                target.write_bytes(original.read_bytes())
            files.append({'path': str(target.relative_to(rom)),
                          'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    if entry not in text:
        gateway.write_text(text.replace(anchor, anchor + entry, 1))
    if service_name not in manifest_text:
        manifest.write_text(manifest_text.replace('    </application>',
                service + '\n    </application>', 1))
    if route not in long_press_text:
        long_press.write_text(long_press_text.replace(anchor_when, anchor_when + route, 1))
    if icon_anchor in homepage_text:
        homepage.write_text(homepage_text.replace(icon_anchor, icon_choice, 1))
    return {'files': files, 'native_settings_fragment': True,
            'compact_sidebar_icons_preserved': True,
            'launcher_activity_added': False, 'manual_qs_tile': service_name,
            'gateway': str(gateway.relative_to(rom))}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = prepare(args.rom.resolve(), Path(__file__).resolve().parents[1])
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
