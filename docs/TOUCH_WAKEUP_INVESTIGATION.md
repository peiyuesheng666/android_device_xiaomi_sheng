# sheng 双击亮屏：控制接口与失败记录

2026-11-07。当前实现是待实机验证的设备树候选，不能列为已修复。
未改公共源码，未启动原厂 TouchFeature HAL，未停止正在工作的 THP 报告服务。
候选模块尚未加载到平板；以下临时 proc 试验已撤回。

## 失败试验与撤回

试验前 `/proc/xm_htc_gesture_switch` 和 `/proc/xm_htc_gesture_dbclk` 都是 0。
在设备 Dozing 时直接写入 1，前者回读 1，后者仍回读 0。
唤醒后再次写 dbclk，日志报告扩展命令发送成功，但仍回读 0。
这说明发送成功不能作为硬件状态已生效的依据。

用户随后报告普通触摸失效。主任务将两个节点恢复为 0，并完成一次息屏、唤醒；
用户确认触摸恢复。此试验必须保持失败状态，不得合入永久配置。

| 内核单调时间 | 观察 |
| --- | --- |
| 1871、1967 秒 | 同一原厂触控固件下载成功，尚未试验 |
| 2133 秒 | 直接 proc 写入 gesture_switch=1 |
| 2163–2164 秒 | 唤醒时 reset 状态和 CRC 读回全 0，固件下载失败 |
| 2173–2214 秒 | 息屏日志为 gesture_command:01；随后的多次唤醒重复固件下载失败 |
| 2272 秒 | 主任务将两个节点恢复为 0 |
| 2288 秒 | gesture_command:00 的息屏、唤醒恢复正常；同一固件更新成功 |

原始 logger 文件保存在 [touch/20261107-direct-proc-failed](touch/20261107-direct-proc-failed/)。
event6 文件为空，表示该限时记录未捕获事件；不能单凭空文件断言 IRQ 或硬件完全没有事件。
PowerManager 记录和用户反馈均未证实双击唤醒成功。

## 原厂内核证据

以固件包实际二进制为依据，不使用其他设备或新内核的 Xiaomi UAPI 推定接口。

| 二进制 | SHA-256 |
| --- | --- |
| `nt36532_touch.ko` | `a1f3f907f4519eaf3d63243561fc32c7f75337188a3953b3857bcad60135233f` |
| `xiaomi_touch.ko` | `da9accaffbd76a339c12e998757ccc3406973b6bf41f72bca615a81752e5c791` |
| `msm_drm.ko` | `9b672fae4fdce22ecaaaf0b1ab52ed5cd1aa9591eb72a6396969296d4e77fdf4` |

`nt36532_touch.ko` 的 `nvt_set_cur_value` 在 `0xbb24..0xbb50` 处理 mode 14：
根据开关只改变 gesture 的 bit 0，保留其他位，然后调用 `nvt_set_gesture_mode`。
bit 0 是触摸唤醒；bit 1 是笔快捷手势。

`nvt_set_gesture_mode` (`0xfe1c..0xff94`) 按 IC 状态处理请求：

| IC 状态（结构偏移 0x270） | 原厂行为 |
| --- | --- |
| 0：开始 suspend | 请求暂存到 pending（0x278） |
| 1：完成 suspend | 请求暂存到 pending |
| 2：resume 中 | 请求暂存到 pending |
| 3：完成 resume | 更新 active（0x274），调用 `dsi_panel_doubleclick_enable` |

`nvt_ts_resume` 在 `0xfce4..0xfd00` 进入状态 3，消费 pending 后将其清为 -1。
直接 proc setter (`0x16378..0x16398`) 仅把 active 归一化为 0/1，
没有上述 pending 处理、其他位保留或 DSI 联动。

`msm_drm.ko` 的 `dsi_panel_doubleclick_enable` (`0x18fa7c..0x18fa90`)
写入 `g_panel+0x8e9`。同一标志用于 `dsi_panel_pre_prepare`
(`0x1627fc..0x162814`) 和 `dsi_panel_post_unprepare`
(`0x164434..0x16444c`) 的 regulator 保持/切换分支。
直接 proc 单独开启触控手势会让触控模式和面板供电标志不一致。
这与试验中唤醒读全 0、恢复后同固件成功相符；完整 mode 14 路径的实测仍待完成。

`gesture_dbclk` 是另一个直接发 SPI 扩展命令 17 的接口，不是 mode 14 的等价替代。
永久实现不得写该 proc，也不得配置 qtipower 直接写这两个 proc 节点。

## 固件请求路径

`nvt_ts_resume` 的默认参数字符串是 `novatek_ts_fw.bin`，但实机日志明确由
`update_firmware_request` 动态解析为 `novatek_nt36532_n81a_fw_csot.bin`。
实际文件 `/odm/firmware/novatek_nt36532_n81a_fw_csot.bin` 存在，大小 245760 字节。
试验前后都会出现 Direct firmware load 的 -2，再经过 sysfs fallback 成功。
因此默认文件名不存在和 Direct load -2 不能单独视为本次触摸故障。
失败点是后续 SPI/reset/CRC 状态全 0，而非当前固件文件缺失。

## 用户指定参考包

只读取、未执行 `E:/6/玩机资源/修复方案/ColorOS双击亮屏及背光修复-长待机.zip`。
SHA-256：`81aae662ef593455b932795f4498e4dab49db7173b956535db0a3930b727870e`。
本次只参考双击亮屏部分，不实现包中的背光、笔或显示设备别名改动。

该包采用 panel 0 / mode 14 的 touchfeature_v2 ioctl，在真实 DRM DPMS 为 On 并
等待一秒后同步开关；Off/AOD/未知状态不发送 ioctl。
它注明曾在 sheng ColorOS、SELinux Permissive 下测试三轮物理双击；
未验证重打包后的冷启动、USB 断开或数小时深睡。
这些历史结果不能代替当前 Lineage 候选的验证。

当前原厂 `xiaomi_touch_dev_ioctl` (`0x3664..0x3708`) 校验 type=0x54、
命令 0 的 size=520。命令 3 的 panel selector 使用整数参数 0；
因此 `0x5403` 与同 nr/type 的 `0x40005403` 对本次 panel 0 选择等价。

| 字段 | 偏移/长度 |
| --- | --- |
| panel，uint8 | 0 / 1 |
| operation，uint8（set=0） | 1 / 1 |
| mode，uint16（double tap=14） | 2 / 2 |
| count，uint16（1） | 4 / 2 |
| reserved，uint16（0） | 6 / 2 |
| data，int32[128]（data[0]=开关） | 8 / 512 |

总长 520，命令号 `0xc2085400`。候选在编译时断言大小和 data 偏移。

## 设备树候选与验收

模块为 `ShengTouch`、`libsheng_touch_jni`、`libsheng_touch_control`、
`sheng-touchctl`，源码位于 [触摸接口](../interfaces/input/touch/)。
2026-11-11 已接入产品包和 system_ext/public/private/vendor policy；历史兼容映射、
host NDEBUG 及 core-to-vendor neverallow 问题修正后，正常模块与策略构建通过。

平台签名的 system UID persistent/directBootAware 应用监听当前用户的
Secure `double_tap_to_wake`、显示状态转变和用户切换。
配置由内容观察者和显示事件触发，刷新率/亮度/几何变化不会反复应用。
JNI 仅在真实 DPMS 连续 On 一秒且请求未取消时发送 mode 14，
在开设备后、selector 前和 mode 命令前再次检查状态。
显示 Off/Doze/Unknown 取消待办，不作触控写入；系统开关仍由 Secure 保存，下次 On 重新读取。
不存在常驻屏幕/settings 轮询、唤醒锁、定时亮屏或休眠闹钟。
重启应用会重新读取真实开关，读不到设置不会默认打开。

CLI `--check` 只读配置/DPMS并报告 hardware=unverified；
`--set 0|1` 同样执行稳定 On 检查和完整 mode 14 路径。
proc 只用于 readback，回读配置不等于物理唤醒成功。

已通过 host 状态机测试（OFF、取消、开设备后/selector 后息屏、ABI、关闭、
失败和未知回读），JNI C++ 语法检查及当前已编译 framework.jar 的 javac 检查。
临时 native CLI 使用同一控制库，息屏时返回 Deferred 且未配置；亮屏时
mode 14 开启回读为 1。用户确认三轮物理双击亮屏及普通触摸正常；对应
固件下载全部成功。关闭后用户确认双击不亮，电源键唤醒及触摸正常，
随后用同一 mode 14 路径恢复开启。未使用 proc setter。
这段试验仍由 rooted CLI 发起，不能代替最终应用域的 Enforcing 权限验证。
随后 r48 正式刷入并重启，应用运行在 u:r:sheng_touch_app:s0，SELinux Enforcing。
系统设置变为 0 时应用自动回读 0，用户确认双击不亮且电源键唤醒触摸正常；
设置恢复 1 时自动回读 1，用户确认三轮物理双击亮屏及每次触摸正常。
普通触摸采集无 SYN_DROPPED，框架 PID 与 boot ID 保持。未发起相机或 AON。
长待机、断开 USB 的深睡以及真正关机冷启动仍未验收。

由主任务审阅并安排后，先验证普通触摸、开关关闭、三轮物理双击、
息屏期间零配置 ioctl 和唤醒固件成功；再验证重启、用户切换以及断开 USB 的长待机。
任一步影响普通触摸或出现固件下载失败，应立即撤回并继续保持失败记录。
高采样率路径仍指向不存在的 bump_sample_rate，报告率/游戏模式尚未确定，不猜测 mode。
