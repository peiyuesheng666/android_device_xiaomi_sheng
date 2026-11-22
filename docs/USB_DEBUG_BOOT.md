# USB 调试开机初始化

sheng 使用 QTI AIDL USB gadget HAL（`sys.usb.configfs=2`）。正常启动时，`usbd` 只在 `persist.sys.usb.config` **精确等于 `adb`** 时启动 `adbd`；其他值走 MTP 默认功能分支。运行中的文件传输、网络共享等 USB 功能由 `UsbDeviceManager` 和 QTI HAL 管理。

此前设备调试 RC 在加载持久属性后强制写入 `mtp,adb`，并直接写 `sys.usb.config`。这与 `usbd` 的启动约定不一致：系统设置可以显示调试已开启，但启动服务未按 ADB 分支执行。关闭再开启调试后，框架显式启动 `adbd` 才恢复。实机日志记录了开机后 USB 先配置、随后断开，以及后续 `adbd_auth` socket 不存在。

调试 RC 改为只设置持久默认值 `adb`，由正常启动路径启动服务并配置 USB。保留系统 RSA 授权；不循环切换调试、不定时重启 USB、不强制维持 MTP。该 RC 仍只安装在 userdebug/eng 产品。

验收应包括至少一次完整重启：不触碰 USB 调试开关，主机自动连接；系统启动完成后保持连接，授权记录仍有效。随后验证文件传输和调试开关仍由系统设置控制。源码检查不能替代重启实测。

2026-11-15 的局部部署复测发现，旧校验脚本在 `sys.boot_completed=1` 后执行 `adb root`，主动重启 adbd 并使 USB 重新枚举。13:49 启动出现一次断开重连；移除这条非必要校验命令后，13:53 的正常启动在至少 87 秒观察窗口内保持 CONFIGURED、没有 DISCONNECTED 事件，ADB 保持普通 shell 身份。校验应使用普通 shell 读取哈希、服务及 USB 日志，避免把主机主动切换 adbd 身份产生的重连误判为设备树启动故障。后续真正需要 root 的局部部署仍须单独记录这类预期重连。
