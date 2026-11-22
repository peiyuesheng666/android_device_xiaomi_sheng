# 普通 Focus Pen 协议

普通 Focus Pen 的 Bluetooth SIG vendor 为 34，product 为 `0x4d80` 或 `0x3280`，使用控制器 type 3。Pro 的 product 为 `0x5081` 或 `0x3281`，使用 type 8。身份必须来自完整七字节 PnP，来源为 Bluetooth SIG，并与实际连接设备匹配。

`ShengStylusSupport` 管理共享身份和本机初始化协议。普通版使用对应的 32 字节参数、双 ID 阶段、频率、电压、时间及吸附状态；Pro 专属的屏幕和移动命令不发送给普通版。

报告解析必须与型号、Report Map 和压力范围对应。Pro 的十五字节 report 5 不能直接用于普通版。电量也按设备地址归属，换笔或无有效读数时不能复用上一支笔的数值。

显示请求通过 `DisplayRateLease` 管理，支持模式应取自设备能力；结束会话或进程退出后自动释放。具体服务入口见 [Focus Pen 接入](FOCUS_PEN_INTEGRATION.md)。
