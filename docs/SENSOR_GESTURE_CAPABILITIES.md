# sheng tap-sensor capability correction

2026-11-12: installed in r61 on ca10ede3 A, with the retained 5.15.220 kernel
and separately accepted r59 Recovery. Normal build, packaged/installed resource
and property checks passed. The user confirmed double-tap wake still works.

## Observed mismatch

The captured r53 product sets `ro.vendor.sensors.xiaomi.double_tap=true` and
`ro.vendor.sensors.xiaomi.single_tap=true`. SensorService lists both generic
LineageOS tap sensors, and SystemUI Doze registers both with result `OK`.
The current standard `double_tap_to_wake` setting is 1; the separate Doze
single/double tap settings are absent and use framework defaults.

The generic implementation depends on these four paths:

```text
/sys/class/touch/touch_dev/gesture_single_tap_state
/sys/class/touch/touch_dev/gesture_single_tap_enabled
/sys/class/touch/touch_dev/gesture_double_tap_state
/sys/class/touch/touch_dev/gesture_double_tap_enabled
```

Read-only checks on ca10ede3 found all four absent (`ENOENT`). The Android log
also records repeated `sensors.xiaomi: Failed to write enable` messages for
both enable paths at 09:20:34, 09:29:49 and 09:29:54 UTC. Raw session evidence
is under `reports/device/20261112-device-continue`: `gesture-sensor-baseline.txt`
contains the property/settings and SensorService baseline; `gesture-node-errors.txt`
contains the four missing-path errors; `baseline-logcat.txt` contains the six
enable failures. These are Android 5.15 observations, not
evidence about the independent 6.18 kernel task.

In manifest-pinned `hardware/xiaomi/sensors/v2/SensorsSubHal.cpp`, the two
properties unconditionally add `DoubleTapSensor` and `SingleTapSensor`.
`Sensor.h` binds them to the paths above. `Sensor.cpp` stops the polling thread
when the state path cannot be opened; the sub-HAL still lists the sensor and
returns `OK` from activation. Registration success therefore does not establish
a working event source. Adding permissions cannot provide the absent nodes.

## Device-tree correction and retained wake path

Set both generic sensor properties to false, clear `config_dozeTapSensorType`
and `config_dozeDoubleTapSensorType`, and remove the six init chmod/chown
commands targeting the absent single/double tap paths. Keeping empty resource
values explicitly prevents Doze from advertising these unavailable sources.
The remaining sensor modules, calibration and SELinux mappings are unchanged.

The accepted double-tap-to-wake feature keeps `config_supportDoubleTapWake=true`.
The manifest-pinned Settings `TapToWakePreferenceController` uses that boolean
for availability and writes `Settings.Secure.DOUBLE_TAP_TO_WAKE`.
`ShengTouchApplication` observes that same setting and applies the original
THP mode 14 through its device-owned native backend. It does not subscribe to
either generic tap sensor. The previous mode-14 disable/enable trials and r48/r49
reboot acceptance remain recorded in `bluetooth-touch-batch-20261111.md`.

Doze uses distinct `DOZE_TAP_SCREEN_GESTURE` and `DOZE_DOUBLE_TAP_GESTURE`
settings. `AmbientDisplayConfiguration` derives their availability from the
sensor-type resources, and the original SystemUI `DozeSensors` looks up those
types in SensorManager. Clearing these resources removes the unavailable Doze
gestures without changing the standard double-tap-wake setting or its backend.
The user subsequently confirmed physical double-tap wake after r61 installation.

## Reviewed references

The three device reference branch heads were refreshed with `git ls-remote`
on 2026-11-12; relevant files were read at their exact commits. Public build
repositories were inspected at the existing manifest-pinned revisions.

| Repository | Commit | Applicability |
| --- | --- | --- |
| xiaomi-pad-8-pro-development/android_device_xiaomi_piano, seventeen | `8c0bb4b9d15ea349eaa09d6de0aa4fec43f7ff41` | The framework overlay enables standard double-tap wake; it does not declare these two generic Doze sensor strings. Board values and implementations are not copied. |
| LineageOS/android_device_xiaomi_nuwa, lineage-24.0 | `8e2b6ca4375919035587115189760eed64f14b8d` | The phone uses sm8550-common configuration; no sheng gesture-node implementation is supplied by its device tree. |
| LineageOS/android_device_xiaomi_sm8550-common, lineage-24.0 | `62f4b9c1d20c88f02e0bc7f1b2c932bd5c750eb1` | Its vendor properties and framework overlay enable these sysfs-backed sensors. Those declarations require board interfaces absent on this sheng baseline. |
| hardware/xiaomi | `c3de4412ad6317b820c8cef7c5e80b7cceb4acda` | Defines the property-gated generic sensors and their fixed sysfs paths. |
| frameworks/base | `696a5773fa284f53429dbb6c3e5dcc96bf5bd0b3` | `AmbientDisplayConfiguration` and `DozeSensors` consume the two Doze sensor resources separately from standard double-tap wake. |
| packages/apps/Settings | `2f16bfe2c784623a324350cd19dae7f6066e2cfb` | `TapToWakePreferenceController` retains the standard switch through `config_supportDoubleTapWake`. |

## Validation boundary

r61 subsequently passed the normal build, exact image delta/metadata checks,
actual split-policy compilation, AVB and all 14 installed partition/dependency
hash checks. Both generic properties are false, both effective Doze strings
are empty and neither tap sensor is registered. The standard switch remains 1
and the user answered “可以正常双击亮屏”. See
[DEVICE_CONTINUATION_R61.md](DEVICE_CONTINUATION_R61.md) for the receipts.

On 2026-11-12 source checks passed: the overlay XML parses, both generic sensor
properties are false exactly once, both Doze sensor strings are empty, the
standard double-tap-wake capability remains true, and init contains no operations
on the four absent paths. The scoped diff also passed `git diff --check`.
These checks establish configuration consistency only.

Before runtime acceptance, build the affected product outputs normally, verify
the resulting properties/resources and partition metadata, install the reviewed
batch, and confirm SensorService no longer lists these two unavailable sensors.
After screen-off/on transitions, check for new generic gesture enable failures.
The user must verify the standard switch remains available, disabling it prevents
double-tap wake, enabling it restores physical wake, and ordinary touch plus
sleep/resume behavior remain correct. Do not mark single-tap wake or other
unexercised sensors as implemented by this capability correction.
