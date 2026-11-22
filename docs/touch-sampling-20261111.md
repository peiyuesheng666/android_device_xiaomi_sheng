# Touch sampling and report rate, 2026-11-11

The user requested lower touch latency by raising touch sampling rate. The
generic Lineage HAL currently targets the absent bump_sample_rate node. Nuwa's
sm8550-common reference uses that path, but it does not exist on this sheng;
piano does not enable a high-polling service. Do not treat those settings as
working sheng hardware support.

Stock nt36532_touch.ko (a1f3f907f4519eaf3d63243561fc32c7f75337188a3953b3857bcad60135233f)
reports awake hand_scan_rate 180. A captured finger-motion interval on event6
contained 699 SYN_REPORT frames; contact tracking retained 695 single-finger
reports and 690 intervals within individual strokes, with no SYN_DROPPED.
The median interval
was 6.948 ms, approximately 143.93 Hz. Firmware scan frequency and delivered
evdev report frequency are separate measurements, not end-to-end latency.

Disassembly of nvt_init_touchmode_data and nvt_set_cur_value verified mode 0's
initialized boolean range and native game command, distinct from gesture mode
14. A bounded device-owned native probe tested that path only while the panel
was stably On. Game-mode readback changed to 1, but scan-rate readings remained
180; the user's sliding/clicking remained normal. The attempted comparative
evdev captures contained no events, so they cannot prove report-rate changes.
The probe restored mode 0 to 0; no permanent game-mode control is integrated.
Mode 9 has no initialized range or hardware setter in the reviewed stock path;
other device enums must not be guessed. No direct proc writes were used.

The stock THP host processor reads n81a_nova_thp_config.ini. Its report_rate
section contains rate_default=240, rate_normal=120, rate_game=240, plus its
existing interpolation configuration. The new device-owned configuration
changes exactly rate_normal=120 to rate_normal=240, leaving every other byte
unchanged. It tries the already supplied 240 Hz reporting profile during
normal operation; it does not establish higher firmware scanning frequency.
The existing host processor is kept, with no runtime service stop or restart.
This candidate will be loaded at the shared batch reboot and must be measured
before claiming a latency or sampling repair. The broken optional high-polling
HAL switch remains a separate unresolved issue.

Original live/OEM configuration SHA256:
cb75e8cf9128f9ea6177d8276d440dc16f55db8f068f7644e94668cfc8f6e2c5.
Candidate SHA256:
9ba104e0ea2bd9c4b843e11989607be5de3a8c107f6d92b3a0a596bf39d64f2c.
The OEM input is read-only; the edited copy and first-precedence product copy
rule live in this device tree. The packaging review must verify the exact
single-setting byte delta and the actual normal-build ODM output.

The normal r48 build produced the exact candidate hash above. The new bounded
capture helper keeps the evdev reader running for a bounded configurable window
(120 seconds by default, 600 for the resumed human trial) and discovers
the physical NVT touchscreen handler from /proc/bus/input/devices. It saves and
flushes each event while waiting for the human trial. The analyzer tracks contact
IDs, excludes multi-finger frames and stroke boundaries, rejects gaps outside
0.1--50 ms, and requires at least 500 intervals without dropped events before
reporting sufficient evidence. The baseline file passes this classification;
an empty trial still provides no evidence of improvement or failure.

Post-r48 valid measurement: 2079 frames, 2019 single-finger reports and 1959
within-stroke intervals; median 6.951 ms / 143.86 Hz, p10--p90 6.740--7.158 ms,
no dropped events and no intervals below 5 ms. Firmware readback remains 180
while On. The user confirmed normal sliding/tapping. This candidate did not
increase report cadence relative to the approximately 144 Hz baseline.

An event-driven comparison switched only the already verified stock boolean
game mode after capturing baseline motion and restored it automatically. The
phase analysis excludes 100 ms around each completed native transition, tracks
contact IDs and checks dropped events. Baseline/game/restored medians were
143.97/143.90/144.05 Hz (503/650/514 intervals), all sufficient and with zero
drops. The user confirmed 25 seconds of normal continuous sliding. Thus the
stock game command also did not increase cadence in this configuration.
It is restored to 0; screen_off_timeout is restored to its original 60000 ms.

The unreferenced candidate copy rule is removed from the device tree; its exact
tested bytes remain only in reports/device/20261111-simple for diagnosis.
r49 restored the unchanged OEM configuration through its existing normal build
module. The output and installed file match the original hash above. Its ODM
and vbmeta were flashed and all six current partition hashes plus declared
payload files match. Enforcing, the stock report daemon and the touch application
remain active. The user confirmed normal touch and physical double-tap wake
after this final reboot. High sampling and the generic HAL switch remain
unresolved. Next work must identify a real stock THP rate-control path or a
supported device-owned backend; do not advertise 240 Hz, lower latency or a
working high-polling toggle from these results.

## r50 stock userspace report control (installed)

The user accepted third-party tablet layouts and prioritized touch sampling.
Decode the actual supplied executable, not only libtouchreport.so: it embeds
the report algorithm and listens on abstract UNIX stream @thp_socket. Its
520-byte messages share the V2 layout above. Operation 0 is the userspace
setter, operation 1 the getter; setters acknowledge with count=0, getters
return ASCII payloads. The live daemon's mode-0 getter returned `0\n`.

In the executable, command processing starts at 0x6d8fc. The mode setter's
uint16 jump table is at 0x1ef2c with target base 0x6e2fc. Mode 202 targets
0x6e9bc: normalize the supplied value to a boolean and update only the
super-report available/current flags at state offsets 1778 and 1779. It does
not send a driver command or change the game/gesture state. Mode 9 remains
unsupported here too. The mode-0 userspace game branch differs from the old
driver-only mode-0 trial and also enables interpolation.

First userspace game comparison: baseline 143.72 Hz (819 intervals), game
287.94 Hz (676), restored 143.79 Hz (640), zero dropped events. The native
collector was stopped after all analysis windows were sufficient, before its
larger final frame goal; it confirmed restoration. Second comparison using
only mode 202: 143.77 / 287.98 / 143.84 Hz (822 / 648 / 824 intervals), zero
drops, native frame goal completed, daemon game state remained 0 at both
transitions. The user confirmed normal sliding/tapping in both comparisons.
Raw events and classified JSON are in reports/device/20261111-simple:
touch-rate-r50-socket.* and touch-rate-r50-report-only.*.

These are increased delivered reports produced by the original interpolation
algorithm, not proof of 288 Hz physical scans or reduced end-to-end latency.
The user explicitly chose to connect this report switch first, then pursue
the original advertised 360 Hz physical sampling mode. Prior 180 Hz firmware
readings were taken after movement; a further bounded trial will read firmware
hand_scan_rate while the captured contact is active to rule out adaptive idle
behavior. The current-reading maximum is not the controller's proven limit.

The device-owned candidate replaces the generic absent-sysfs polling HAL with
the same standard IHighTouchPollingRate interface. Its fixed mode-202 socket
backend preserves mode 0/14. A typed persistent vendor property stores the
requested state. The vendor HAL observes DPMS and replays after stable On,
with at most five attempts per wake/request transition. No new sampling command runs while Off;
socket transfers have deadlines and validate the OEM peer/ack. Settings labels
describe report frequency. The firmware INI stays byte-identical to stock.
Host checks cover Off/cancellation, invalid values, enable/disable, transport
failure and rejecting game/gesture/malformed acknowledgements. Product build,
strict policy/VINTF/AVB packaging, installation, wake and persistence validation
remain pending. Original SystemUI and public/kernel sources remain untouched.

The firmware-contact trial completed with 143.95 / 288.06 / 143.76 Hz delivered
cadence (824 / 648 / 831 intervals), zero drops, and hand_scan_rate=180 while
captured motion was active in all three phases. This does not restore 360 Hz
physical scanning. The user also observed approximately 287 in their test app,
accepted this result, and asked to integrate it into the system as-is. Further
physical 360 Hz exploration is deferred for this batch; finish the verified
report toggle and its installation/physical wake regression first.

The first normal build rejected a direct socket connection from the core touch
application to the vendor report daemon under the existing Treble neverallow.
That path was removed rather than weakening policy: only the vendor touch HAL
owns the mode-202 socket backend and wake restoration. The existing application
keeps its previously verified mode-14 behavior. The rebuilt product must pass
the original neverallows and the actual partition policy combination.

The corrected normal module build passed. Both scoped mirrors checked 43
inputs, and the fresh public audit verified 1243 clean repositories. r50's
actual partition policy compiled with the original neverallows, VINTF was
compatible, and the complete retained AVB chain verified. Five images were
flashed to ca10ede3 A. All six current partition digests and declared files
match; the original SystemUI and firmware INI remain unchanged, Enforcing is
active, and the existing mode-14 application remains in its dedicated domain.

The first boot reused the old ShengTouch directory parse cache (version 37).
Changing only the APK's reproducible mtime does not expire this cache: the
platform compares the package directory's mtime against cache creation time.
The exact single parse entry was backed up and moved out; after reboot the
system correctly identifies version 2.0. The scoped installer now performs
this same narrow cache invalidation before flashing. No app data is cleared.

The four-window system-setting trial completed without dropped events, but
additional standard-setting changes contaminated the first two windows.
Retain its expected_cadence_passed=false result; do not call all four windows
successful. The final stable disabled/enabled pair has 825/846 usable intervals
and medians 143.8849/288.0184 Hz. User confirms normal sliding/tapping, fast
boot, immediate touch after boot and screen-off behavior. Mode-202 wake replay
acknowledgements were observed. The requested high state is left enabled.
At the r51 reboot (1755ec7d-1e85-43fe-9e08-1464d6eb0a64), both the persistent
report property and standard system setting read back 1, and the HAL is running.
This verifies enabled-state persistence; no new physical cadence capture was
performed at that boot.

The isolated WSL face-policy sources were restored byte-for-byte from their
backup after packaging. Deferred face sources on Windows were never changed.
