# Cross-application media routing (r52 installed)

After accepting the r51 page repair, the user identifies Douyin as still lacking
audible Dolby processing. The active app is com.ss.android.ugc.aweme, UID 10134.
Its original session 169 plays 44.1 kHz stereo media through primary output 13.
AudioPolicy attaches the enabled global DAP_offload control there, but the
queried active speaker graph at AGM session 125 / AIF 31 contains no DAP tag.
Independent read-only queries of unchanged OEM calibration confirm that deep
buffer graph A1000001 has DAP instance 4615, while low-latency A100000E and
generic A1000014 do not, even with speaker DevicePP AC000002 selected.

The device tree explicitly sets audio.deep_buffer.media=false. The unchanged
upstream AudioPolicyConfig reads this property for each output selection.
AudioPolicyManager::getOutputForDevice uses DEEP_BUFFER for stereo MUSIC only
when the requested flags are NONE and sample rate is supported. Explicit FAST,
MMAP, direct, non-media and voice requests preserve their selection. The r52
device-tree candidate restores this standard property to true. This can select
the existing 109 ms deep-buffer output instead of the 63 ms primary output;
the normal platform playback timestamp and video synchronization apply. It
does not repair missing DAP in explicitly requested fast/game paths.

The user reopened Douyin and confirms a clear audible change when switching
Dolby and adjusting Custom EQ. The later AudioPolicy snapshot places its new
session 233 on output 21 (deep_buffer). It was inactive by dump time; retain
that limitation. PAL live tracing during the interaction identifies DAP 4615
and shows parameter 10904 written/read back as 0 then 1 twice, all result=0 and
matches=1. Subsequent direct GETs after playback paused returned -22; those
are not an active-graph success claim. Trace property was reset to false.

Evidence lives in reports/device/20261111-simple/dolby-cross-app-r51:
douyin-audioflinger.txt, douyin-audiopolicy.txt, douyin-dsp-session-scan.txt,
acdb-*-stock.txt, douyin-trial-accepted-audiopolicy.txt and
douyin-trial-accepted-dsp.txt. The read-only probes are compiled from device-tree
tools; no public sources, stock calibration or original libraries were edited.

Normal vendor/build.prop build passed in 1:35; the scoped mirror matches its
one input and the fresh public audit confirms all 1243 repositories clean.
The package comparison retains every original duplicated property occurrence;
the only semantic delta is audio.deep_buffer.media false -> true. EROFS metadata
is preserved, vendor/build.prop is its only changed file, and the complete AVB
chain verifies. vendor and vbmeta were flashed to ca10ede3 A. Six partition
hashes and declared files match, Enforcing is active, and r51 Dolby controls,
r50 enabled touch state, original SystemUI and all policies are retained.

At boot c6e5e6a5-fe21-435d-9620-e6ded15e0479, the property is already true from
the installed image. The user confirms Dolby remains audible on the first
Douyin playback without re-toggling, and sound/video are synchronized. A fresh
active capture shows UID 10134 / session 73 on output 21 (deep_buffer), global
DAP enabled, and AGM session 125 / AIF 31 now reports tag C00000DB / MID 100108DB
/ MIID 4615. Native enable 10904 and state parameters 10748, 10743, 10738 all
return status=0, error=0, value=1. Diagnostic query 08001026 returns -131 on
this DAP module; retain it rather than claiming every diagnostic parameter
is supported. This does not replace the successful DAP-specific enable query.

Post-boot evidence: r52-douyin-live-audioflinger.txt,
r52-douyin-live-audiopolicy.txt, r52-douyin-live-dsp.txt and r52-native-state.txt
in the same directory, plus r52-runtime-readback.json and
r52-dolby-media-acceptance.json in its parent. This accepts the reproduced
Douyin ordinary-media route. Explicit fast/game routes and additional apps
remain outside the acceptance scope; accessory audio and USB internet were
not re-tested at this reboot.
