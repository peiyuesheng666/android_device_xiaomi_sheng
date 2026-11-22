# Recovery 菜单启动与电池监控

2026-11-13 更新：设备电池 UI 扩展、Recovery 策略与固件初始化入口的正常
模块构建和产物验证已通过，修复了正常构建遗漏的启动脚本/策略输入。
详见 [RECOVERY_PRODUCT_INTEGRATION.md](RECOVERY_PRODUCT_INTEGRATION.md)。
此次未打包或安装新镜像；完整产品及下述未完成的实机范围继续保留。

2026-11-12，当前 r59 已安装在 ca10ede3 Recovery A，固件路径修复沿用 r54，
非阻塞 UI 沿用 r55，电池事件监听沿用 r56。系统仍为 r53 键盘批次。
两次独立启动的菜单提交为 3.532/3.497 秒，真实 UI 电量为 6.057/6.022 秒；
触摸服务分别运行到启动后 20.28/20.25 秒，未出现启动退出。
已经自动返回 Android；未安装人脸或手写笔候选。

## 原因与实现

原 ScreenRecoveryUI 电池线程首次读不到 supply 时，会在持有 updateMutex 的
情况下重试最多五秒。r54 已使 ADSP 正常启动，但供电节点约七秒才就绪，电池线程
仍占据约 2.7 秒的绘制锁，阻塞菜单显示。两条 Qualcomm DRM 的“Atomic Commit
failed”日志对应返回值 0，源码条件写反；不能以这两条提示认定显示提交失败。

设备树定义 `librecovery_ui_sheng`，通过 TARGET_RECOVERY_UI_LIB 接入标准
Recovery 扩展点。ShengRecoveryUI 继承原 ScreenRecoveryUI，保留菜单、输入与
图形后端；在 base 初始化前标记原电池线程停止，等待其退出后启动自己的读取线程。
读取 battery/capacity、status 和重试均发生在绘制锁外，只有字段更新与重绘持锁。
数据尚未出现时显示 `--%`，有效数据到达后显示实际百分比；失败时保留上次有效值，
不生成默认 100%。析构先停止并等待两个绘制相关线程，避免线程越过派生对象生命周期。
原 Recovery 的升级低电量检查与 health 服务仍使用原有实现。

## r59 首次电量与驱动加载顺序

r56 的事件监听已生效，但 release 名称的模块目录使本 ROM 的 init 固定走
LoadListedModules；bootconfig 的 conservative 参数并未真正启用并行。
切换扁平目录的 r57 确实达到八个同时加载，却把 block2mtd 放到了 UFS 之前，
模块等待约 3.07 秒，随后分区又等待约 2.14 秒，菜单和电量都变慢。

r58 把 block2mtd 后移，电量缩短至 5.411 秒，但触摸运行程序启动后以 status 6
退出再重启；第二次启动也捕获 restarting。此前只检查当前 running 会漏掉这个
故障，所以 r58 不保留为稳定修复，验证工具已增加启动退出记录和 20 秒观察。

r59 恢复原来的顺序加载，保留电池事件监听与日志模块后移。Recovery 的
modules.load.recovery 仅移除 block2mtd；其 mtd 依赖仍在第一阶段，没有其他
模块依赖 block2mtd。存储冷启动和 fs 完成后，独立 oneshot 服务读取原 BSP
cmdline 参数，确认设备解析到专用 oops 分区，再后台加载日志模块。
服务两次都返回 0，`/proc/mtd` 确认对应设备；不阻塞菜单、ADSP 或 health。

| 镜像/启动 | 菜单提交（秒） | 首次真实 UI 电量（秒） | 验证结论 |
| --- | --- | --- | --- |
| r55 | 4.485 | 7.010 | 用户确认菜单变快，仍反馈电池同步慢。 |
| r56 | 4.499 | 7.024 | 事件监听工作；并行参数未生效。 |
| r57 | 8.550 | 9.976 | 并行已开启，存储加载顺序拖慢启动。 |
| r58 首轮 | 4.169 | 5.411 | 触摸启动退出后重启，稳定性不通过。 |
| r59 首轮 | 3.532 | 6.057 | 顺序加载，触摸启动后 20.28 秒内无退出。 |
| r59 第二轮 | 3.497 | 6.022 | 不同 boot_id，触摸启动后 20.25 秒内无退出。 |

以上都是内核启动后的 CLOCK_BOOTTIME，包含 bootloader 的总入场时间未测量。
r59 比 r55/r56 的菜单与首次电量均提前约一秒；电池仍需等待 ADSP/PMIC 通路，
不能称为无延迟。实际菜单触摸、物理充电切换和非满电百分比仍需用户验收。

r59 第一阶段加载 334 个模块，后续补回 block2mtd，共保留 r55 的 335 个已加载
模块；全部 336 个打包模块哈希相同。metadata 只调整 recovery 加载清单，
dep/softdep/alias 及二进制索引保留。扁平目录另有 release → `.` 兼容链接，
bootconfig 明确关闭并行。设备树 device.mk 已接入独立 Recovery init 与脚本
复制项，正式产品构建尚未通过。

r59 镜像 AVB、重新解包、库/策略/脚本和 A 槽分区回读通过；Recovery B、
boot A、dtbo A 不变。全局 Enforcing，原 Recovery 域名单保持。
启动时早期固件挂载仍可能在 coldboot 前失败，fs 重试后完整固件就绪、ADSP
自动运行；没有把早期请求记为成功。两轮 ADSP 启动为 3.738/3.704 秒。

Android 已返回，sys.boot_completed=1、zygote/system_server 运行，A 槽、
5.15.220 内核、144/144 设置及 report_high=1 保持。触摸 HAL、高频服务、
指纹、键盘和杜比进程运行。当前 crash buffer 有一次 dolbycodec2 在查询
HEVC 编码接口时因 HIDL DEAD_OBJECT 退出，进程已重启；媒体编码问题继续
独立排查，不能将此回读记作完整硬件/媒体回归通过。

证据在 `reports/device/20261112-recovery-pen/` 的 `r59-first/`、
`r59-runtime.json`、`r59-dmesg.txt`、`r59-late-dmesg.txt`、`r59-package.json`
和 `r59-android-final.txt`。r59 镜像 SHA-256：
`03605520d3889050f628e9076a81b2a2700c10d8655da0155e1ce57635529769`。
公共 system/core、bootable/recovery、build/make、vendor/lineage 已重新 fetch
其 manifest 固定版本并通过文件字节检查，见 `r57-upstream.json`。
电池事件实现详见 [RECOVERY_BATTERY_EVENTS.md](RECOVERY_BATTERY_EVENTS.md)。

## r55 历史验证

源代码以固定 ROM 的原 Recovery 头文件和 r54 实际库为依赖，scoped native
编译及无未定义符号链接通过；当前 Recovery 的动态加载检查通过。新模块已定义
普通 Soong 构建入口，但当前产品 ninja 图在此前资源受限分析中截断，正常模块与
完整产品构建均未通过，不能将本次 scoped 构建计作整包成功。

r55 只替换 ramdisk 中 `system/lib64/librecovery_ui_ext.so`；AVB 与解包全部内容
校验通过。内核、DTB/DTBO、模块、策略、固件路径脚本和文件模式保持。
镜像、UI 扩展、策略与脚本实机回读一致；Recovery B、boot A、dtbo A 哈希保持。
全局 Enforcing，保留原有 Recovery permissive 域名单，没有新增域放宽。

首轮启动日志：首菜单提交为内核启动后 **4.485 秒**，实际 UI 电量首次更新
**7.010 秒**；healthd 首次有效数据为 7.011 秒，ADSP 4.698 秒启动。
原电池重试日志消失，菜单先于电池数据提交，约 2.5 秒的界面锁等待被消除。
这不是包含 bootloader 在内的总开机秒数，也不能证明全部黑屏过渡已消除。
用户对速度、触摸及电量的运行反馈尚待记录；当前满电，非满电对照仍待验证。

随后已返回 Android，sys.boot_completed=1、A 槽和 Enforcing 正常；触摸 HAL、
高频报告服务、键盘进程和原版杜比进程运行。report_high 仍为 1，最低/最高刷新率
为 144/144；crash buffer 为空。Recovery A 保持 r55，boot A、dtbo A 哈希匹配
刷写前基线。此回归是服务/状态检查，物理触摸与键盘完整回归尚未由本轮重新验收。

证据位于工作区 `reports/device/20261112-recovery-pen/` 的 `r55-ui-build.json`、
`r55-package.json`、`r55-runtime.json`、`r55-recovery.log`、`r55-dmesg.txt`。
镜像 SHA-256：`d4f9f9b2258fa3949f57c84c82707208368cdfa7dee3c7bf9bb64fe66c6ed5c3`。

参考 ROM 提交见 [RECOVERY_FIRMWARE_PATH.md](RECOVERY_FIRMWARE_PATH.md)；
公共 bootable/recovery 固定在 `c1ccd0b4a17557f97ed864b96f160674609c1c54`，已重新
fetch 并检查无工作树改动。相关默认 UI/扩展点和锁行为来自此版本，无公共源码修改。

在本机 WSL 中，r59 使用保留的 r58 输入及 r56 UI 构建收据：
`tools/package_sheng_recovery_ui_r55.py --revision 59`。
验证使用 `tools/verify_sheng_recovery_firmware_r54.py --revision 59 --adb /path/to/adb.exe`。
源 UI 的 scoped 编译仍由 `tools/build_sheng_recovery_ui_r55.py --revision 56` 提供。
构建工具依赖本机保留的 r54 解包库，正式产品通过普通 Soong 模块构建相应扩展。

## 2026-11-12 用户验收

用户在本次设备树续修中，对 r59 的进入速度、菜单触摸和电量显示明确回复
“已经正常”。结合上述两轮启动、触摸服务和分区回读证据，将 r59 的这三项
实际体验记为通过；此前缺少用户菜单/触摸反馈的状态已补齐。

这条反馈没有给出具体的非满电对照百分比，也不代表完整 Android 产品构建、
全部 Recovery 功能或完整硬件回归通过。Android 当前仍为 ca10ede3 A 的 r53；
本次反馈未触发新的 Recovery 刷写或重启。
