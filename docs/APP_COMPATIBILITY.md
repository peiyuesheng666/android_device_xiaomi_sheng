# 通用大屏应用窗口适配

设备树通过 Android 上游窗口兼容策略，让符合条件的应用使用平板的实际全屏窗口。
不按 APK 包名配置，也不修改 framework、Settings 或应用源码。

## 正常构建入口

- `configs/device-config-defaults` 通过 `device.mk` 安装到
  `/system/etc/device-config-defaults`。
- 文件仅有一行 `window_manager:ignore_activity_orientation_request=enabled`，
  使用上游 ConfigInfrastructure 的一次性引导接口。
- Framework RRO 启用上游应用宽高比设置和全屏选项。
- 游戏、应用明确的调整大小限制、用户明确选择的宽高比继续遵循上游例外。

该引导依赖当前 Android 17 上游实现；移植到其他 ROM 时需要核验对应接口。
引导文件只处理一次，OTA 不会自动重跑。不得删除
`device_config_bootstrap_values/processed_values` 来强制重置用户状态。

## 实测范围与限制

r12 临时验证中，固定竖屏应用的居中窗口从
`Rect(874, 0 - 2175, 2032)` 变为 `Rect(0, 0 - 3048, 2032)`，
应用配置为 `sw813dp`、横屏，`isLetterboxRunning=false`。
设备的 `ro.build.characteristics=tablet`、物理密度 400dpi 已正常。
用户确认窗口全屏、主要界面正常，但内部排版仍有手机界面观感。

全屏窗口和应用原生平板界面分别记录：多栏、平行页面和控件布局取决于
应用提供的界面与行为，窗口适配不等于这些功能已经完成。
生产配置面向全部符合上游条件的应用，抖音仅用作已安装应用的验证样本。
不更改应用 APK，不以修改全局密度伪造平板布局。

## 重启验收

临时验证后删除测试 DeviceConfig key，恢复原始 null 状态；刷入前确认
一次性引导命名空间仍为空（parser 检查其中任意 key，不仅是标记值）。
正式镜像启动后检查引导文件、标记和窗口策略，
重新打开样本应用并检查实际窗口，再由用户确认显示和交互。
编译、刷写和重启验收结果另记，临时成功不作为持久修复通过。

当前上游依据为 `DeviceConfigBootstrapValues.java` 第 34、71–116 行，
框架 bool 定义为 `core/res/res/values/config.xml` 第 6756、6759 行。
此版本的 framework-res 没有 overlayable 定义，ODM 预装策略允许现有 RRO
覆盖这两项；其他 ROM 仍需检查自身 overlayable 和 idmap 策略。

## 2026-11-21：默认未铺满实机复查（待修）

在 `ca10ede3` 上只读确认 Framework RRO 已启用，且
`/system/etc/device-config-defaults` 包含预期行；但
`device_config get window_manager ignore_activity_orientation_request` 返回 `null`，
`device_config list device_config_bootstrap_values` 无输出。引导文件存在不等于策略已生效，
也不能单凭这项结果判定所有未铺满应用的根因。下一步核对实际构建使用的引导实现及消费日志，
用复现应用确认是全屏窗口的兼容留边还是桌面模式的自由窗口。验收应覆盖未设置过宽高比的
应用首次启动、旋转和重启，并保留用户自行选择的比例及上游例外。不要用全局密度、按包白名单
或清除数据来代替修复。本次未修改实机设置。

进一步核对：元数据命名空间区分大小写，源码实际使用
`DeviceConfigBootstrapValues`。实机 `device_config get DeviceConfigBootstrapValues processed_values`
返回 `true`，而目标策略仍为 `null`。因此当前源码的引导逻辑不会在这台已处理过引导的设备上重放；
尚未证明目标键是首次未写入，还是后来被移除。前台微信 `LoginAsExDeviceUI` 实测任务模式为
`fullscreen`，任务范围 `Rect(0, 0 - 3048, 2032)`，活动窗口范围
`Rect(894, 0 - 2155, 2032)`，`isLetterboxRunning=true`，原因为 `FIXED_ORIENTATION`。
这次样本确认是固定方向兼容留边，不是桌面自由窗口。修复需覆盖已有数据升级路径，
不能只依赖一次性引导；不重置引导标记或覆盖用户选择。

补充排除：实机 `wm get-ignore-orientation-request` 已是 `true`（display 0），
但 `dumpsys window` 仍显示 `ignore_activity_orientation_request_screens=none`。
这两项不是同一个开关。当前平台源码 `WindowManagerConstants` 从 DeviceConfig 计算
`all` / `large` / `none`，`ActivityRecord.canBeUniversalResizeable()` 读取这个结果，
同时保留游戏及受限调整大小的例外。单独增加 `display_settings.xml` 的
`ignoreOrientationRequest=true` 不应作为这个问题的修复。Framework 资源
`config_letterboxIsPolicyForIgnoringRequestedOrientationEnabled` 也是不同机制，
处理应用运行时调用 `setRequestedOrientation`，不是此处的默认可调整大小策略。
