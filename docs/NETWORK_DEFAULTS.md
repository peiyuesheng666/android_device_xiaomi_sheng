# 默认校时与联网检测

设备树通过 FrameworkResOverlaySheng 将网络校时服务器设为
`ntp://time.apple.com`。NTP 提供 UTC 时间；自动时区仍使用系统原有的检测机制。
`properties/system.prop` 将首次启动的默认时区设为 `Asia/Shanghai`；
后续启动加载已有持久属性，保留用户选择的时区。

NetworkStackResOverlaySheng 安装在 product 分区，覆盖 NetworkStackConfig
中的 HTTP、HTTPS 和地址数组。主检测地址为小米
`connect.rom.miui.com/generate_204`，备用为华为
`connectivitycheck.platform.hicloud.com/generate_204`，均保留相应协议。
系统继续执行真实的联网与门户认证检测。

这两项均为编译进 ROM 的资源默认值，无需首次启动脚本或手动 ADB 配置。
已有的用户 NTP 设置或 NetworkStack 实验配置可能具有独立优先级，排查时应检查运行状态。

## 2026-11-21 packaging / runtime gate

- Both overlay modules are in `device.mk`; this is source inclusion, not proof
  of image inclusion. The retained product and ca10ede3 lack the sheng
  NetworkStack RRO. The retained NetworkStack APK exposes all five configured
  probe resources under `NetworkStackConfig`.
- The installed framework RRO is enabled, but its idmap does not map
  `array/config_ntpServers`. `cmd overlay lookup android
  android:array/config_ntpServers` and `dumpsys network_time_update_service`
  both show Android NTP. The retained framework APK's overlayable dump does
  not list the NTP array. Verify resource-policy compatibility against the
  exact candidate framework before calling this fixed; an enabled overlay or
  a successfully built APK alone is not sufficient.
- Release gate: verify both RROs in the generated image, verify the target
  mappings and resolved values, then check a real HTTP/HTTPS validation and
  successful Apple NTP refresh on the tablet. Keep validation enabled and
  do not conflate NTP with automatic time zone.
