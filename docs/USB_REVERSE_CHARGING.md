# USB 反向充电

设备组件 `interfaces/usb/power` 编译为平台签名的系统应用 `ShengUsbPower`，由
`device.mk` 纳入产品。没有桌面启动图标，不依赖 Pixel 专有接口，也不修改 SystemUI。

- 电池页通过 Settings 的 `EXTRA_SETTINGS` 和 EntriesProvider 协议使用系统自己的
  `SwitchPreferenceCompat`。开关放在 `percentage_category` 的电量百分比下方、充电控制
  上方，不设图标、子页面或点击跳转。组件必须作为系统应用预装才能显示。
- `USB 反向充电` 快捷块由用户在下拉面板编辑页手动添加。
- 系统 USB 端口广播触发低优先级的持续通知。通知显示实际受电／供电方向，点击进入
  电池页；拔线后取消。无需常驻服务，不发声或自动打开弹窗。
- `default-permissions-sheng-usb-power.xml` 为预装组件默认授予通知权限，用户仍可修改。

开关使用 `UsbPort.setRoles()`，优先保持现有数据角色；电池页在不支持单独交换供电角色
时允许系统声明支持的 source/host 或 sink/device 配对。只有 USB HAL 声明支持相应角色组合
时才请求切换，不直接写入充电驱动的 sysfs 节点。亮／勾选状态来自端口实际角色；请求
尚未完成时显示切换中，8 秒后未成功则报告失败。未连接设备时开关不可用。

关闭反向充电表示请求切回受电角色，不能保证连接对方不会继续供电；完全停止双向供电
需要拔线。与原装充电器连接时不能保证能够反转，手机、线材也必须支持相应角色。

构建：在 WSL 中运行 `tools/build_sheng_usb_power.py`，复用本机 ROM 的 framework、
AAPT2、D8 和平台签名。正常 ROM 构建直接编译 Soong 模块。临时部署工具
`tools/install_sheng_usb_power.py --serial ca10ede3` 在上传和写入临时文件后检查 SHA256，
然后通过同目录重命名部署独立 APK 和默认权限文件；不自动重启，不替换系统现有 APK。

2026-11-18 16:06，用户确认已成功为小米 10S 充电。系统日志记录角色切换成功，
`power_role` 为 source，数据角色维持 device；电池状态为放电。用户同时确认电池页
位置和样式正确。记录保存在 `reports/usb-reverse-20261118-success`。

15:57 的另两次连接曾出现 SET_PDR 命令后 CCI 持续 BUSY，内核等待同步完成确认超时，
触发 PPM 重置；记录在 `reports/usb-reverse-20261118-1557`。本组件补全入口和真实状态
回读，不能据一次成功认定这个底层间歇超时已经修复，未因此修改内核或固件。

本功能与原装 120 W 快充实际输入功率不足的排查独立，不更改快充、电压、电流或温控策略。

## 2026-11-18 低功率反充排查（尚未修复）

用户用功率表测得约 5 V、1 A，约 5 W；小米 10S 和小米 11 Ultra 在
40–50% 电量时均有此现象。同样接法在官方系统曾达到约 20–30 W（用户实测反馈，
本次尚无官方系统的对应协议抓取），因此不能将当前低功率解释为硬件上限或接近满电。

16:55 的复测确认平板为 source/host，低功率并非只出现在 source/device 组合。
UCSI GET_PDOS `0x700010010` 请求本机最多四个 source PDO，完成 CCI 为
`00 04 00 80`，只有四字节有效数据 `96 90 01 36`，即一个固定档位
`0x36019096`：5 V、1.5 A，公布的 PD 上限 7.5 W。响应缓冲区剩余十二字节
是旧内容，不能继续解码成其它 PDO。该档位不是实测输出，也不代表硬件最终能力。
另外两个 source selector 的 GET 查询返回相同内容，但尚未验证固件是否区分这些 selector。

原厂 `batterysecret` 与当前 ROM 引入文件 SHA256 相同：
`71016e312de1af8eeaea662cd18c39d6f825289c028a07aa71b1e7ecfee70daa`。
不能据此认定运行条件、内核接口或认证过程完整一致。日志中的
`reverse authenticaon result:0` 也不能单独判为认证失败：该程序对命令返回文本调用
`atoi()`，内核反充认证命令的读回分支可以返回 `8,Null`。

原厂通用 MiCharge 配置包含 `reverse_quick_charge`，但 sheng 原厂充电模块本身
没有此节点字符串，当前设备也没有该节点；不能凭通用配置就补写一个电气控制接口。
原厂 CIT 配置将 `/sys/class/qcom-battery/reverse_chg_mode` 指定给笔的无线反充测试，
因此没有尝试将它用于 USB 提功率，也没有套用其它型号的反充属性。

本次只读取系统、内核及 UCSI GET 诊断，并短暂开启充电固件日志。
固件日志配置已回读确认恢复为 enable/category/level = 0/0/0。
记录在工作区 `reports/usb-reverse-power-20261118/source-host-retest/`，
含原始系统日志、内核日志、UCSI IPC 和校验过有效长度的 `decoded.json`；
固件记录在 `reports/charging-firmware-20261118-165543/`。

当前结论限于：供电开关确实已切换，协议查询仍只返回低功率档位；
高功率反充协商缺失的原因尚未确定，没有部署提功率补丁。

17:06 的进一步查询：本机 source 仍为 5 V / 1.5 A，本机 sink 返回 5 V / 3 A；
手机侧的 source/sink 查询均成功完成，但有效返回长度为零，不能从残留响应缓冲区
推断手机支持或拒绝了某个档位。手机 PD revision 字段为 0.0，也不能据此断言手机
没有 PD。新增 `tools/capture_sheng_reverse_power.py` 同时保存系统、内核和接口状态；
加 `--query-pdos` 后只发送 UCSI GET_PDOS，按对应 IPC 的 CCI 有效长度解码。
无有效 IPC、错误 CCI、取消、BUSY 或越界长度均不解码。解析器的故障检查已通过。

另发现一处独立的 USB 服务权限缺陷：`vendor_hal_usb_qti` 读取 `sysfs_udc` 目录
被拒绝。当前 Qualcomm `Usb.cpp` 在 UDC remove 事件后会 `opendir("/sys/class/udc")`；
失败时将目录视为空并设置 USB ADB disabled 属性。sm8550 公共策略只允许目录 search。
设备树 `sepolicy/vendor/hal_usb_qti.te` 补充目录只读权限，使这条控制器枚举路径能够执行。
这解释了一个 USB 插拔恢复隐患，不足以证明它导致或修复了 5 W 反充。

该规则与此前传感器隔离候选策略合并后已通过 checkpolicy、策略版本化和最终
neverallow 校验；尚未部署或实机验证。构建结果见
`reports/usb-reverse-power-20261118/udc-policy-build.json`。

17:12 的插拔记录保存在 `reports/usb-reverse-power-20261118/replug-171236/`。
该次插入后平板实际是 sink/host；`pd-auth:1` 和 cmd6 超时均发生在受电阶段，
不能用它们判定反向供电认证成功或失败。

17:15 通过现有电池开关请求反向供电，确认成功切到 source/device，平板处于放电。
同步固件日志明确记录手机请求第一个固定供电档位、工作及最大电流均为 1500 mA，
随后 `PD_SRC updated source current:1500`、
`PmicTccPlatform_Schg_PDPhy_R1_HW_SetOTGCurrentLimit ... 1500 configured`。
这次有效 PDO 查询仍只有本机固定 5 V / 1.5 A；手机 sink 查询则有两个有效 PDO：
`0x2601912c`（固定 5 V / 3 A）和 `0x990191f4`（可变 5–20 V / 5 A）。
后者仅表示手机公布的受电范围，不表示平板支持这些电压或正在输出该功率。
系统报告 `is_power_transfer_limited=false`，未发现 Android 限制传输开关开启。

本次已确认限制出现在实际 PD 合同和固件 OTG 限流配置，不能靠显示功率或改变
界面开关修复；为何只公布低档位尚未确定。当前加载路径中的全部 57 个 `adsp.*`
文件与本地原厂提取件 SHA256 相同，不能将问题直接归于 ADSP 固件版本不一致；
运行时策略、初始化及其它组件仍需排查。没有修改电压、电流、认证或温控限制。
反向供电保持开启，固件日志 enable/category/level 已回读恢复为 0/0/0。

原始记录：`reports/reverse-power-20261118-171535/`、
`reports/charging-firmware-20261118-171505/`；文件比较记录：
`reports/usb-reverse-power-20261118/adsp-firmware-comparison.json`。

## 2026-11-18 17:46 插拔复测

用户确认故障表现为间歇性：角色切换时好时坏。此次经无线 ADB 记录用户拔插并再次开启反向供电的过程，资料位于 `reports/reverse-auth-20261118-continued/`。

- 本次成功进入 source/device；固件 `pe_src_state_ready_init` 同时报告 PowerRole=1、PDContractState=1、VDMContractState=0。
- 手机再次请求固定第 1 档 1500 mA，固件随后报告 `PD_SRC updated source current:1500`。此次成功切换仍然没有协商到高功率。
- 同一时段固件的 XM CURRENT_STATE 查询返回 31，sysfs 因而显示 SNK_Ready；Type-C 与 PD 状态机则报告 source。该不一致由固件响应可见，不能直接归因于 sysfs 缓存或改写状态字符串来修复。原厂模块反汇编同样将 31 映射为 SNK_Ready、5 映射为 SRC_Ready。
- batterysecret 此次记录 `connect with phone not do authentic`、pd-auth=0、UVDM_STATE=0。这仅表明该程序走到这条分支，尚不足以证明它是高功率缺失的根因。
- 角色切换的间歇超时和成功切换后的低功率均仍未修复；本次未部署推测性内核更改。
- 诊断脚本完成后打印 RESTORED，独立回读确认 charger_ulog enable/category/level 均为 0。
