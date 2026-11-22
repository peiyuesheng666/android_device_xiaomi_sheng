# Recovery 电池事件刷新

2026-11-12，设备树的 ShengRecoveryUI 在 r55 非阻塞读取基础上增加
NETLINK_KOBJECT_UEVENT 监听。原来取得首个有效值后每五秒轮询；现在过滤
power_supply 和 battery_charger 事件，字段变化后重绘，每秒读取作为丢事件兜底。
连续事件的最短读取间隔为 100 ms，所有读取和等待仍在绘制锁外。
节点尚未就绪时保持 `--%`，读取失败保留上次真实值。

socket 建立失败会明确记录并使用定时读取；退出检查和事件排空都有边界，
析构仍等待电池与进度线程结束。未改变原 Recovery 的升级低电量检查。

r56 的 scoped native 编译、无未定义符号链接及安装通过，原始启动日志记录了
100% 状态从 Discharging 到 Charging、再到 Discharging/Charging 的实际更新。
这覆盖启动中的真实供电状态变化；没有进行物理拔充电器或非满电百分比对照。
r59 保留同一个 UI 二进制，SHA-256 为
`dd48f34f21e0c2bcd013ee2bcdc84f658da72ad9470ff4b19e1a27531d93bcd9`。
两次独立 r59 启动均记录事件监听启用及实际电量更新。

证据在工作区 `reports/device/20261112-recovery-pen/` 的
`r56-ui-build.json`、`r56-startup-trial.txt`、`r59-first/r59-recovery.log`
和 `r59-recovery.log`。2026-11-13 普通 Soong UI 模块、Recovery 策略及
产物核验已通过，详见 [RECOVERY_PRODUCT_INTEGRATION.md](RECOVERY_PRODUCT_INTEGRATION.md)。
完整产品构建仍未通过，本批未新增镜像安装或实机验收。
模块加载及首次电量时序另见 [RECOVERY_UI_STARTUP.md](RECOVERY_UI_STARTUP.md)。
