# Remaining device-tree work after r52

2026-11-11: r52 installed ca10ede3 A, SELinux Enforcing. User accepts fast boot,
immediate touch after boot, normal sliding/tapping and screen-off behavior.
Third-party tablet layouts (including Bilibili's initial aspect-ratio prompt),
LHDC v5 playback/reconnection, USB RNDIS sharing, double-tap wake and initial
144 Hz settings are accepted. r50's standard report switch delivers about
144/288 Hz in the final stable disabled/enabled windows and remains enabled.
Enabled-state persistence was verified at the r51 reboot: property/system key
both remain 1 and the report HAL is running. r51 also repairs Dolby switch
clickability; the user accepts master, dialog-enhancement and Custom EQ controls.
Physical 360 Hz scanning is explicitly deferred; interpolation is not IC sampling.

| Work | Remaining scope |
| --- | --- |
| More audio-app coverage | r52 fixes the reproduced Douyin ordinary-media route; post-reboot DAP query, audible effect and video synchronization are accepted. Additional apps and explicit fast/game paths remain unverified. |
| Native FaceUnlock — deferred by user | Genuine Settings enrollment, authentication and lock-screen validation; r46 is not installed. |
| Xiaomi keyboard | Attachment/removal, shortcuts and associated services. |
| Xiaomi stylus | Charging/pairing, contact/hover, buttons and app cooperation. |
| Xiaomi Notes | Source/dependencies and pen/keyboard integration. |
| Recovery | Entry black-screen interval and battery readings. |
| Fingerprint | Authentication after extended standby and repeated sleep. |
| Display/media | Color accuracy, HDR, DRM, encoding and additional app paths. |
| Other sensors/thermal | Only the still-unverified functions and file-creation scenarios. |
| 6.18/product builds | Matched Android partition integration, full product and regression; consume finalized work from the other kernel task. |

All changes stay under device/xiaomi/sheng. Only operate ca10ede3, retain original
SystemUI and public/kernel/OEM sources, and keep already accepted fixes.

