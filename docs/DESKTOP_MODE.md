# 桌面模式与快捷按钮

原生入口是“设置 → 系统 → 互动 → 桌面模式”，不增加桌面或应用抽屉入口。

“启用桌面模式”只控制平板内屏。开启后应用使用桌面窗口；关闭后返回全屏。
用户选择保存在 `Settings.Global.sheng_desktop_enabled`，缺省为关闭。
窗口恢复和应用重开都需要遵守这个选择。关闭状态下，普通全屏应用不显示桌面拖动横条。

内屏的 `DesktopDisplayModeController` 也必须读取同一选择。键盘、触控板在唤醒时
重新注册会触发它重新计算显示模式；原有自动键盘策略未读取此开关，会在关闭状态下
重新把内屏任务显示区域设成自由窗口。`display-mode-policy.patch` 在盛机内屏策略
入口优先使用保存的选择，开启时仍检查桌面能力。外接显示器继续走原有策略。
准备工具随构建应用此补丁；需要重建 SystemUI。
2026-11-18 候选已编译，但安装时连接中断，系统 APK 校验不一致。
已恢复此前版本并修复重新识别应用后丢失的蓝牙运行时权限，用户确认界面恢复。
16:09 再次安装时，已先上传完整文件、核对 SHA256、保留 SELinux 标签，再原子替换。
重启 SystemUI 后暴露 READ_CONTACTS 运行时权限缺失，已补回并记录；没有清除应用数据。
16:10 完成关闭、开启、再关闭三轮实际熄屏／唤醒测试：Shell 的目标窗口模式和
`Display#0 isDesktopFirst` 均与选择一致。测试后已恢复原选择 0 和 fullscreen，
记录为 `reports/desktop-wake-live-20261118-161058/result.json`。
再次安装使用 `tools/install_sheng_desktop_wake_policy.py` 的同目录临时文件与原子替换；
不得直接覆盖运行中的系统 APK。安装前保存包权限与备份，检查蓝牙和用户资料所需权限，
安装后仍需验证启动和唤醒。Android toybox 不支持 chcon --reference，工具读取并校验
原文件的 SELinux context 后设置临时文件标签。

下拉快捷设置，进入编辑页面，可以手动添加“桌面模式”和“杜比全景声”。
两个按钮均以灰色表示关闭、点亮表示开启，点击直接切换。桌面按钮与原生设置页面同步；
杜比按钮读取现有音效控制器的实际状态。锁屏时先解锁。源码不主动将按钮加入面板。

辅助显示器沿用系统扩展桌面策略，页面不再提供重复的辅助显示器开关。
内屏桌面开关不替代 DP、USB-C 转 HDMI 的链路与兼容性配置。

设备源码保存在 `interfaces/display/desktop`，构建前由
`tools/prepare_sheng_desktop_settings.py` 注入原生 Settings，由
`tools/prepare_sheng_desktop_shell.py` 应用设备限定的 Shell 窗口策略。
PixelOS 的 `tools/build_hardware.sh` 在扫描源码前执行这两个准备步骤。
修改 Shell 后需要重新构建 SystemUI；修改页面、按钮或图标后需要重新构建 Settings。
构建、安装身份与运行验证保存在工作区 `reports`，不以说明文档替代运行记录。

当前预装的平板 Pixel Launcher 内嵌另一版框架的私有资源编号，其桌面能力判断中的
`0x011101f3` 在本版框架指向 `config_hideNavBarForKeyboard`，导致桌面切换控制器未创建，
快速切换桌面任务会抛出 `recentsController is null`。设备的 `properties/system.prop`
默认设置 `persist.wm.debug.desktop_mode_enforce_device_restrictions=false`，让启动器使用
已有的能力检查覆盖入口。该属性需要重启桌面进程才能生效；不更改导航栏资源、启动器
APK 或桌面数据。内屏是否使用窗口仍由 `sheng_desktop_enabled` 控制。更换预装启动器
或框架版本后，应重新运行 `tools/ShengDesktopCapabilityProbe.java` 核对能力判断。

内屏从普通桌面打开窗口时，Shell 的专用壁纸活动会遮住启动器。设备的
`home-transition.patch` 与 `shellsrc/com/android/wm/shell/transition/ShengDesktopHomeTransition.java`
为这一组 Quickstep 过渡补充 250 毫秒的桌面淡出，保留应用窗口原有的动画。
淡出从远端初始事务提交后开始；过渡结束恢复图层透明度，返回桌面的合并过渡会取消淡出。
只有同时包含退出的 Home、进入的桌面壁纸活动和自由窗口应用的内屏启动才应用此策略。
全屏应用启动、辅助屏和其他远端动画不应用此策略。准备工具会随现有 Shell 补丁一起注入，
仍需要重建 SystemUI。`tools/ShengDesktopHomeTransitionProbe.java` 可在 Android 上核对适用范围。

桌面阴影、圆角等要求客户端合成时，设备显示合成服务将该图层至上方最后一个透明图层
之间的非保护内容放进同一个客户端合成目标，避免透明提示条独立硬件叠加时闪动。
没有客户端合成要求的画面继续使用原策略；范围以下的壁纸可继续使用硬件图层。
保护内容位于范围内时不进行这项提升。判断使用原始客户端要求，避免上一帧的
策略选择使下一帧反复切换。实现位于 `interfaces/display/composer/hwc_display.cpp`
和 `client_composition_range.h`，控制属性为 `vendor.display.translucent_client_fallback`
（缺省开启）。修改后需重建 `vendor.qti.hardware.display.composer-service-sheng`。

2026-11-18 版本号闪动复测中，Settings 和 Toast 都走硬件合成，原有要求存在客户端图层的兼容处理未触发。新增 `vendor.display.toast_client_fallback`（缺省开启）候选策略：Toast 存在时，把其下方内容与提示放进一个客户端合成目标；提示上方图层保留原策略，范围内有保护内容时不提升。没有 Toast 时回到原策略。这用于验证提示叠加与闪动的关联，已安装候选但尚待用户确认效果，不是全局关闭硬件合成。

## Keyboard opt-in (source candidate)

The Desktop Mode settings page has a separate `sheng_desktop_auto_keyboard`
switch, defaulting to off. The Shell re-evaluates the internal display on
switch changes and input-device events. With the switch on, an enabled
physical full keyboard requests desktop mode; removing it cancels that request,
without clearing the independently stored manual desktop preference.

Release acceptance requires Settings and SystemUI from the same build. Check
attach, detach, and unlock with automatic switching off and on, verify that
manual mode survives detach, and check the Settings and QS entry points.
The controller compile is not a device acceptance result.

## 内屏默认模式与窗口验收

用户最新复查认为此前看到的比例异常主要发生在桌面模式，先验收桌面模式，不全局修改应用宽高比。
默认或升级后未启用自动切换时，键盘已连接的冷启动、锁屏解锁、热插拔都应留在普通平板模式；
Settings 和 QS 手动入口仍应可用。手动进入后，检查窗口最大化、恢复、退出桌面模式后再打开应用；
普通模式不应沿用桌面的自由窗口尺寸。用同一应用、同一方向比较任务窗口模式与活动实际边界，
区分桌面窗口未最大化与应用在全屏任务内自己的方向兼容留边。

当前实机只读快照：`Settings.Global.sheng_desktop_enabled=0`，
`Settings.Global.sheng_desktop_auto_keyboard=null`，前台微信聊天任务为 `fullscreen`；
两个桌面容器仍存在但均不可见。这只证明采样当时不是桌面模式，不证明冷启动、解锁或键盘插拔通过。
