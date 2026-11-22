# Focus Pen Pro transport review, 2026-11-13

The user physically attempted tapping and writing during
`r53-pro-pressure-live-20261113-215850` and reported that neither works.
Initialization returned ID 1 and the post-initialization timing ACK. Actual
undock and active-state notifications were observed, but there were no valid
pressure reports, THP pressure acknowledgements or NVT pen events. Cleanup
restored the original 60000 ms timeout and its one owned controller connection.

The subsequent complete controller context shows Bluetooth connected and
charge changing between 0 and 1. `enable_last_time` also changes. A stuck dock
flag is therefore not an established cause. The trial tool now additionally
saves complete pen-only context; its old tail of 160 lines could hide this
information behind finger commands and repeated charger notifications.

`ShengPenHidInspect.java` performed read-only GATT inspection of the exact bonded
Pro on ca10ede3 A, with SELinux Enforcing. It checked PnP before reading HID
metadata and made no controller, report, protocol or CCCD writes. Readback:

| Input report ID | Characteristic handle | CCCD |
| --- | --- | --- |
| 1 | 0x0026 | 0100 |
| 2 | 0x002a | 0100 |
| 5 | 0x002e | 0100 |
| 6 | 0x0032 | 0100 |

Protocol mode is 01 (Report). Report 5 has fourteen payload bytes plus its HID
report ID, matching the existing fifteen-byte pressure collector. The GATT
Report Map matches the observed UHID descriptor. The pressure notification
CCCD was enabled at this later readback; it is not a simultaneous trial read.
The temporary information DEX was restored and its exact original SHA-256
`06131a31625d968379ff008c883114d083f79485fa15e48324dc2b21626c4b14`
was verified. No service was restarted or partition installed.

`analyze_sheng_pen_hid_trace.py` reviews the already captured filtered btsnoop
log using these actual report references. The captured LE connection identifies
the exact Pro. All 1055 records have equal original/included lengths and zero
recorded drops; its pen ATT packets are complete and have no continuation
fragments. Incoming notifications consist of 64 MIPP notifications at 0x003c
and 18 keyboard report notifications at 0x002a. There are zero notifications
at pressure handle 0x002e, including during the recorded physical trial.

These results place the observed absence before the pressure collector. They
do not identify the cause in pen initialization, controller signalling or pen
hardware, and do not prove that later CCCD state held throughout the trial.
They do not justify changing public Bluetooth sources, bypassing HID identity
checks, synthesizing coordinates or marking writing fixed.

Receipts, readbacks, retained capture and analysis are under workspace
`reports/device/20261113-full-product/pen-hid-transport-review`. The user feedback
and original trial are recorded separately in `pen-tip-physical-trial.json`.
Ordinary Focus Pen remains without physical hardware acceptance.
