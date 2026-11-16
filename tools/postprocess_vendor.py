#!/usr/bin/env python3
"""Attach device-owned inputs to generated vendor modules, never public source."""
from pathlib import Path

QTI_REQUIRED_BEGIN = '    // BEGIN SHENG QTI BOOTSTRAP REQUIRED\n'
QTI_REQUIRED_END = '    // END SHENG QTI BOOTSTRAP REQUIRED\n'
QTI_PAYLOAD_BEGIN = '// BEGIN SHENG QTI BOOTSTRAP PAYLOAD\n'
QTI_PAYLOAD_END = '// END SHENG QTI BOOTSTRAP PAYLOAD\n'


def remove_qti_bootstrap_installer(text):
    # Normal extraction returns an explicitly selected development installer
    # to the OEM service and removes only its generated companion declarations.
    for begin, end in ((QTI_REQUIRED_BEGIN, QTI_REQUIRED_END),
                       (QTI_PAYLOAD_BEGIN, QTI_PAYLOAD_END)):
        if text.count(begin) != text.count(end) or text.count(begin) > 1:
            raise ValueError('Malformed QTI candidate installer markers')
        if begin in text:
            start = text.index(begin)
            stop = text.index(end, start) + len(end)
            text = text[:start] + text[stop:]
    return text.replace('":sheng-qti-codec2-bootstrap"',
                        '"proprietary/vendor/bin/hw/vendor.qti.media.c2@1.0-service"')


def install_qti_bootstrap(text):
    """Keep the OEM service identity while loading C2 providers in local groups."""
    text = remove_qti_bootstrap_installer(text)
    # Retire the earlier single-executable allocation repair as well.
    original = '"proprietary/vendor/bin/hw/vendor.qti.media.c2@1.0-service"'
    text = text.replace('":sheng-vendor.qti.media.c2@1.0-service"', original)
    marker = '    name: "vendor.qti.media.c2@1.0-service",'
    assert text.count(marker) == 1
    start = text.index(marker)
    end = text.index('\n}\n', start) + 3
    section = text[start:end]
    assert section.count(original) == 1 and 'required:' not in section
    section = section.replace(original, '":sheng-qti-codec2-bootstrap"')
    required = (QTI_REQUIRED_BEGIN + '    required: ["libsheng_qti_codec2_service"],\n'
                + QTI_REQUIRED_END)
    section = section[:-2] + required + '}\n'
    return text[:start] + section + text[end:]


def install_qti_audio_bootstrap(text):
    """Retain the audio HAL installer and its distinct sandbox/registry profile."""
    begin = '    // BEGIN SHENG QTI AUDIO BOOTSTRAP REQUIRED\n'
    end_marker = '    // END SHENG QTI AUDIO BOOTSTRAP REQUIRED\n'
    if text.count(begin) != text.count(end_marker) or text.count(begin) > 1:
        raise ValueError('Malformed QTI audio installer markers')
    if begin in text:
        start = text.index(begin)
        end = text.index(end_marker, start) + len(end_marker)
        text = text[:start] + text[end:]
    original = '"proprietary/vendor/bin/hw/vendor.qti.media.c2audio@1.0-service"'
    replacement = '":sheng-qti-audio-codec2-bootstrap"'
    text = text.replace(replacement, original)
    marker = '    name: "vendor.qti.media.c2audio@1.0-service",'
    assert text.count(marker) == 1
    start = text.index(marker)
    end = text.index('\n}\n', start) + 3
    section = text[start:end]
    assert section.count(original) == 1 and 'required:' not in section
    section = section.replace(original, replacement)
    required = begin + '    required: ["libsheng_qti_audio_codec2_service"],\n' + end_marker
    section = section[:-2] + required + '}\n'
    return text[:start] + section + text[end:]


def install_cacert_runtime(text):
    """Keep the certificate service's dlopen dependency in the product closure."""
    marker = '    name: "CACertService",'
    assert text.count(marker) == 1
    start = text.index(marker)
    end = text.index('\n}\n', start) + 3
    section = text[start:end]
    required = '    required: ["libjnihelper"],\n'
    if required not in section:
        assert 'required:' not in section
        section = section[:-2] + required + '}\n'
    return text[:start] + section + text[end:]


def postprocess_vendor(vendor: Path, *, qti_candidate=False):
    if qti_candidate:
        raise ValueError('The single-main QTI candidate failed teardown and cannot be selected; '
                         'qualify the separate bootstrap/payload before integration')
    bp = vendor/'Android.bp'
    text = remove_qti_bootstrap_installer(bp.read_text())
    needle = '    name: "libar-gsl",\n'
    properties = ('    header_libs: ["libsheng_gsl_headers"],\n'
                  '    export_header_lib_headers: ["libsheng_gsl_headers"],\n')
    assert text.count(needle) == 1
    if needle + properties not in text:
        assert 'libsheng_gsl_headers' not in text
        text = text.replace(needle, needle+properties)
    for name, source, replacement in (
        ('libdlbdsservice', 'proprietary/vendor/lib64/libdlbdsservice.so', ':sheng_dolby_dms_compat'),
        ('libhwdap', 'proprietary/vendor/lib64/soundfx/libhwdap.so', ':sheng_dolby_effect_compat'),
        ('libdlbpreg', 'proprietary/vendor/lib64/libdlbpreg.so', ':sheng_dolby_pregain_compat'),
        ('libdlbvol', 'proprietary/vendor/lib64/soundfx/libdlbvol.so', ':sheng_dolby_volume_compat'),
        ('c2.dolby.hevc.dec', 'proprietary/vendor/lib64/c2.dolby.hevc.dec.so', ':sheng_dolby_video_decoder_compat'),
        ('c2.dolby.hevc.sec.dec', 'proprietary/vendor/lib64/c2.dolby.hevc.sec.dec.so', ':sheng_dolby_video_secure_decoder_compat'),
    ):
        start = text.index('    name: "'+name+'",')
        end = text.index('\n}\n', start)+3
        section = text[start:end]
        if '"'+source+'"' in section:
            section = section.replace('"'+source+'"', '"'+replacement+'"')
            # Only the arm64 client has the isolated ABI. Leave any stock arm
            # client and its dependency list unchanged.
            arch = section.index('android_arm64:')
            section = section[:arch]+section[arch:].replace('"libstagefright_foundation"', '"libshgdolby_foundation"')
            text = text[:start]+section+text[end:]
        else:
            assert '"'+replacement+'"' in section and '"libshgdolby_foundation"' in section
    # Resize only the reviewed GraphicBuffer allocations in the generated
    # library outputs. The original module identities/dependencies stay intact.
    for name, source, replacement in (
        ('camera.xiaomi', 'odm/lib64/hw/camera.xiaomi.so', ':sheng_gb_camera_compat'),
        ('libcom.xiaomi.grallocutils', 'odm/lib64/libcom.xiaomi.grallocutils.so', ':sheng_gb_grallocutils_compat'),
        ('libcom.xiaomi.mawutils', 'odm/lib64/libcom.xiaomi.mawutils.so', ':sheng_gb_mawutils_compat'),
        ('libmis_plugin_vidhance', 'odm/lib64/libmis_plugin_vidhance.so', ':sheng_gb_vidhance_compat'),
        ('c2.dolby.hevc.enc', 'vendor/lib64/c2.dolby.hevc.enc.so', ':sheng_gb_dolby_encoder_compat'),
    ):
        start = text.index('    name: "' + name + '",')
        end = text.index('\n}\n', start) + 3
        section = text[start:end]
        original = '"proprietary/' + source + '"'
        if original in section:
            assert section.count(original) == 1
            section = section.replace(original, '"' + replacement + '"')
            text = text[:start] + section + text[end:]
        else:
            assert section.count('"' + replacement + '"') == 1
    # Keep one installer per original binary path. Source mains compile as
    # non-installable modules; the generated vendor prebuilts consume their ELF
    # outputs, preserving original init/module identities without Make conflicts.
    services = [
        ('dolbycodec2', ':sheng-dolbycodec2'),
        ('vendor.dolby.media.c2@1.0-service', ':sheng-vendor.dolby.media.c2@1.0-service'),
    ]
    qti_input = ':sheng-vendor.qti.media.c2@1.0-service'
    # The single-main candidate has incompatible global C2 symbol ownership.
    # Select the separate local-group bootstrap after the shared fixups below.
    text = text.replace('"' + qti_input + '"',
                        '"proprietary/vendor/bin/hw/vendor.qti.media.c2@1.0-service"')
    for name, replacement in services:
        source = 'proprietary/vendor/bin/hw/' + name
        start = text.index('    name: "' + name + '",')
        end = text.index('\n}\n', start) + 3
        section = text[start:end]
        if '"' + source + '"' in section:
            section = section.replace('"' + source + '"', '"' + replacement + '"')
        else:
            assert section.count('"' + replacement + '"') == 1
        # The platform Codec2 defaults export these dependencies to the source
        # binary. Preserve ELF dependency checks in the prebuilt installer too.
        dependencies = ['libcodec2_hal_common', 'server_configurable_flags',
                        'libaconfig_storage_read_api_cc']
        for dependency in dependencies:
            if '"' + dependency + '"' not in section:
                assert section.count('shared_libs: [') == 1
                section = section.replace('shared_libs: [',
                    'shared_libs: [\n                "' + dependency + '",')
        text = text[:start] + section + text[end:]
    bp.write_text(install_cacert_runtime(install_qti_audio_bootstrap(install_qti_bootstrap(text))))

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('vendor', type=Path)
    parser.add_argument('--qti-candidate', action='store_true',
                        help='Retired: the single-main candidate failed validation; always rejected')
    args = parser.parse_args()
    postprocess_vendor(args.vendor, qti_candidate=args.qti_candidate)
