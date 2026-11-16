# QTI Codec2 integration

The device builds lightweight service bootstraps and separate payload libraries. Each payload constructs the platform ComponentStore using its matching headers and obtains the implementation from the original QTI factory.

| Profile | Binder instance | Factory library | Process |
| --- | --- | --- | --- |
| Video | `default` | `libqcodec2_core.so` | `media.hwcodec` |
| Audio | `default2` | `libqc2audio_core.so` | `media.audio.qc.codec` |

`qti_profile.h` selects the factory, instance, process name and sandbox paths. The factory bridge reads the store getter from the original AArch64 factory interface and retains its library for the process lifetime. A different factory binary requires checking that interface before integration.

The bootstrap has no Codec2 startup dependency. `qti_load_groups.h` opens the field-vector providers in separate `RTLD_LOCAL` groups, then loads the payload. Provider and plugin references remain alive while component and registry destructors run. Audio uses its own provider list.

The generated vendor service modules remain the sole installers for the original executable paths. Source bootstrap modules are not independently installed. Each vendor installer requires its payload; the payload requires the libraries loaded by its profile.

Audio software decoding also needs `libAlacSwDec.so`, `libApeSwDec.so`, `libFlacSwDec.so`, `libEvrcSwCodec.so`, `libQcelp13SwCodec.so` and `libdsd2pcm.so`. The proprietary extraction list supplies these backends. `configs/audio-codec-backends.json` identifies the ALAC, APE and FLAC firmware inputs.

ALAC configuration from the system MPEG4 extractor uses network byte order. `qti_audio_store.h` adapts that configuration at the HIDL input queue, preserving the original QTI component identity and its output pools. Missing optional packet-size and bitrate hints receive bounded estimates for the vendor decoder. The conversion applies only to recognized codec configuration buffers; audio packets and other codecs use their existing paths.

Video uses `codec2.vendor.base-arm64.policy` and `codec2.vendor.ext-arm64.policy`. Audio uses the corresponding `c2audio` policies. The bootstrap applies minijail before loading providers, opening Binder or creating the component store. Init ownership, groups and SELinux domains come from the original service configuration.

For local compilation, `tools/build_sheng_qti_bootstrap_candidate.py --profile video` and `--profile audio` reuse recorded compiler inputs without loading the global build graph. `tools/run_sheng_qti_bootstrap_candidate.py` checks interface and component lifetimes in an independent process. `tools/verify_sheng_qti_service_elf.py` runs the platform ELF checker.

`tools/package_sheng_codec2_service.py` requires an explicit installed baseline and its sealed file contexts. It preserves the other partitions and rebuilds the vendor AVB descriptor. Audio and video processing diagnostics are provided by `ShengAudioCodec2RoundTrip.java` and `ShengCodec2RoundTrip.java`; they use generated input data without recording or displaying media.
