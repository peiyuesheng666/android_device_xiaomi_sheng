# Recovery 默认 ADB

本设备的 userdebug Recovery 默认允许 USB ADB 连接，无需先点击“高级 → Enable ADB”。
设备树在 Recovery 的 `early-init` 设置 `ro.adb.secure.recovery=0`，使用当前 ROM
菜单“Enable ADB”采用的同一个控制属性。Recovery 仍通过原有 USB 配置流程启动
adbd，并在进入 sideload 时切换到 minadbd。

该属性仅由 Recovery 版本的 adbd 读取。Android 系统中的 USB 调试开关、电脑
授权和 `ro.adb.secure` 保持原配置。进入 Recovery 后，连接 USB 的电脑可直接
使用 ADB shell 和文件传输；正常 sideload 安装仍校验更新包。

正常产品入口是 `rootdir/etc/init.recovery.qcom.rc`，独立 Recovery 入口是
`rootdir/recovery/init.recovery.sheng.rc`；两者设置一致。
