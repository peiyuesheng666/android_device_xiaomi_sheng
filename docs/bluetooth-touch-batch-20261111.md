# Bluetooth, touch and display batch, 2026-11-11

The user reiterated multiple independent functional repairs per shared build/
installation and selected Bluetooth or touch before Recovery/keyboard work.
The r47 display-only candidate is sealed but uninstalled; a source-mirror guard
does not count as a second functional repair. Face r46 remains deferred.

REDMI Buds 8 Pro are paired with ca10ede3 A. The user reports complete silence.
Bluetooth negotiates LHDC v5 at 48 kHz / 24 bit / stereo, with selectable
44.1/48/96/192 kHz. Native software encoding repeatedly reads zero of 1440 PCM
bytes, with dropped packets and no actual PCM reads. AudioPolicy routes the
A2DP output through the primary HAL, not the software transport module.

The device policy advertises AUDIO_FORMAT_LHDC on the three primary A2DP output
device ports despite PAL having no LHDC encoder configuration. It includes only
the hearing-aid Bluetooth module, omitting the already installed full software
A2DP transport policy. The candidate removes only LHDC from primary encoded
formats and includes bluetooth_qti_audio_policy_configuration.xml, retaining
the other hardware codec paths and hearing-aid support. Its installed module,
audio.bluetooth_qti.default.so and session libraries are present.

Fresh sm8550-common reference 62f4b9c1d20c88f02e0bc7f1b2c932bd5c750eb1 contains
the same exclusion and full Bluetooth software-policy include. Nuwa device
8e2b6ca4375919035587115189760eed64f14b8d and piano seventeen
8c0bb4b9d15ea349eaa09d6de0aa4fec43f7ff41 were refreshed for this batch. The
manifest-pinned framework's HwModuleCollection selects a hardware module by
the negotiated encoded format. This change adapts the device configuration,
without patching any public audio or Bluetooth source.

A separate boot denial prevents vendor_init from setting
persist.vendor.bt.a2dp_offload_cap. Its correction and transport relevance are
not yet established.

The candidate was temporarily bind-mounted onto the selected vendor audio
policy, with matching vendor_configs_file label, and audioserver restarted
after announcing the interruption. The user then confirmed audible playback
and normal audio after putting the REDMI Buds 8 Pro into their case and taking
them out to reconnect. LHDC v5 remained selected at 48 kHz / 24-bit stereo.
PCM expected/actual advanced from 39877920/13106880 to 41097600/14326560:
both increased by 1219680 bytes; the old underflow count stayed 18591.
Thus this interval delivered all requested PCM with no additional underflows.
This validates the live policy trial, not persistence across reboot. The bind
mount is still active pending the combined installation; no partition bytes
were changed by the trial. Permanent build/flash/readback remains pending.

Touch read-only evidence: the system double_tap_to_wake is 1, while the
controller gesture bit is 0. The existing generic high-polling HAL targets the
nonexistent bump_sample_rate path. The board-owned mode-14 candidate is not
installed. Direct proc writes previously caused firmware/wake failure and
must not be repeated. High-report-rate mode needs stock ABI and measured
controller-event evidence before enabling it.

Raw evidence and build receipts are under reports/device/20261111-simple and
/root/sheng-lineage/hardware-diagnostics/sheng-simple-r47-20261111.
Bluetooth temporary playback and accessory reconnection passed the user trial.
USB standard RNDIS selection was added after the user reported immediate toggle
failure; temporary DHCP and Internet access passed, see usb-tethering-20261111.md.
Touch is now registered with its device-only package, public/private/vendor
policy and exact DPMS/proc labels. The combined normal module build is running;
permanent installation, Enforcing runtime and physical wake trials remain pending.

The temporary native mode-14 ioctl path passed three physical double-tap wake
cycles with normal sliding/tapping afterward. Disabling it prevented physical
double-tap wake; the power key still resumed normal touch. It was restored to 1.
These trials establish the stock hardware path, while the packaged app's
automatic setting synchronization and reboot behavior remain untested.
The r48 build also includes the original THP configuration with only its normal
report profile changed from 120 to the already supplied 240. This is an
unmeasured candidate, detailed in touch-sampling-20261111.md.

The WSL device-source build snapshot retains the installed r44 face policy
without the deferred r46 key namespace. prepare_sheng_bt_touch_batch.py backs
up the r46 source and removes only that device-source block plus its namespace
context from the build checkout. Windows face work remains untouched. Packaging
must reject sheng_face_key and compare direct face rules with the installed
r45 policy, preserving its payload. No compiled CIL is edited by hand.

The normal r48 module build including the THP ODM output completed successfully.
The scoped mirror has 52 matching device inputs; a fresh manifest-pinned public
audit reports 1243 clean projects. The embedded JNI library must be compared
with its stripped Soong output, because embedded packaging does not install a
standalone system_ext/lib64 copy.

Strict compilation of the original five-partition update exposed generated
base_typeattr numbering collisions between the newly compiled system_ext policy
and the older installed product policy. Using the normally compiled product
policy resolves the strict neverallow errors. The final batch therefore also
replaces product_sepolicy.cil and its generated hash in product, and updates
its AVB descriptor in vbmeta_system. The packaging guard checks exact attribute
renumbering, an explicit allowlist of expanded public members for the existing
sheng_face and new sheng_touch_app types, and unchanged original rule statements.
No platform source or compiled CIL is edited. The actual final partition
combination must pass strict secilc without -N, VINTF and complete AVB checks.

r48 was sealed, all strict policy/VINTF/AVB checks passed, and its six partitions
were flashed to ca10ede3 A. Runtime partition and payload hashes match; original
SystemUI remains byte-identical, Enforcing stays active and framework processes
remain stable. The user confirmed audible playback and automatic accessory
reconnection after reboot. Bluetooth dumps show LHDCv5 at 48 kHz / 24-bit stereo.
The user also confirmed permanent USB sharing with an adapter and Internet.
The packaged touch app, in its dedicated Enforcing domain, automatically applies
Secure 0/1; the physical disable test and three enabled wake cycles passed.
The temporary display-user initialization tests passed and their user was removed.

Actual touch-rate measurement rejected the 240-normal-profile candidate: 1959
single-contact intervals had median 6.951 ms (143.86 Hz). A subsequent continuous
stock game-mode comparison yielded baseline/game/restored 143.97/143.90/144.05
Hz, with 503/650/514 intervals and no SYN_DROPPED. The game mode is restored to
0; the original 60000 ms screen timeout is restored. No permanent game-mode
feature is installed. r49 restored the original THP config;
high sampling remains unresolved, with detailed evidence in touch-sampling-20261111.md.

r49 normal-module restoration build and its 51-input mirror guard passed; the
fresh upstream audit again found 1243 clean projects. The exact OEM configuration
was restored with an ODM/vbmeta-only update, and complete AVB verification passed.
Every other ODM file retains its original content and metadata; policy and VINTF
inputs stay identical to strict-verified r48. Final runtime readback verifies all
six current partitions, every declared payload, original SystemUI, RNDIS,
display version, touch node labels and active stock/app touch processes in
Enforcing. The user confirmed ordinary touch and physical double-tap wake after
this second reboot. Bluetooth/USB functional acceptance was observed after the
r48 reboot; their vendor and product payloads were unchanged by this restoration.

The temporary WSL face-policy isolation was restored from backups matching the
Windows source after r49 packaging/building completed. This restores deferred
source work for a later face task; no r46 policy, key namespace or face payload
was built or installed into this batch. A later non-face policy build must again
isolate that deferred source instead of silently installing it.
