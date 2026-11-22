# sheng 适配持久记忆

## 2026-11-17：反馈机暂不可接，仅继续软件验证；控制器回归补齐

用户明确回答反馈机暂不能通过 ADB 连接，只继续软件验证。本轮不要求安装候选，
不刷 USB 正常平板、不启用旧模块，完整包仍须等待普通笔实机验收。

增加 PenShortcutControllerTest，编译并执行实际 PenShortcutController、PenLaserView、
PenButtonState、PenModel、PenControls，Android 服务/菜单/截图边界使用 host doubles。
覆盖普通笔三键分工、重复 down 去重、Pro 380ms 保留、原始屏幕坐标、输入身份/来源/
显示屏排除、过期位置、悬停进出复用、释放/超时、暂停/关闭、旧 generation 动作拒绝、
addView 失败后重试、锁屏/用户切换/非交互限制，以及不消费输入/不注入加号。
共 49 项控制器断言及原有 86 项 View 断言通过，不等于 Android 合成或真实笔可见性。

先复现后修复：shortcut-controller-before-fix/receipt.json 在异常长度报告取消激光
断言失败；原控制器 state.clear 后未移除激光，并且 report(null) 在 eligible 时会
访问 report.length。现在拒绝报告同步取消激光任务，null 安全；不符合 eligible 的
真实笔事件清除缓存位置并关闭激光，避免锁屏后继续显示或复用旧位置。该状态缺陷
是软件复现，不得将它冒认为第六份日志“激光不可见”的已证实根因。

最终整套回归：reports/ordinary-pen-feedback6-20261117/run-o48tp_vb/receipt.json。
APK v9/1.8-test 位于 Desktop/普通版手写笔应用-v9-20261117/ShengStylus.apk，构建校验
见 reports/ordinary-pen-apk-v9-20261117/apk-build-receipt.json。它取代 v8 候选，勿要求
用户反复试装；所有 source/harness、framework、fixture 哈希留档。配套 native 构建
记录在同一 run 目录。压感仍需要匹配 vendor 组件实机生效后验收，不能靠 APK 宣称已修好。

## 2026-11-17：先软件测试，再普通笔实测，最后完整包

用户最新顺序：先继续修复和软件测试；普通笔测试通过后再打完整包。不得因
旧的完整包目标而提前打包、刷当前正常 USB 平板，或宣称硬件问题已解决。

本轮软件回归通过：reports/ordinary-pen-feedback6-20261117/run-dqkhfkho/receipt.json。
两份反馈日志的 3127/2029 条压力报告回放，通过实际 PenHidEndpoint、PenController、
PenHardware；THP 对端为 host double，ASAN/UBSAN 下检查 188569/123343 项。
其他检查：native controller 143，协议 31，按键 97，GATT actor 167，输入恢复 46，
充电 94，激光 View 86。另有输入身份排除测试。actor 增加真实 report2 订阅回调，
普通/Pro native-only pause(-2) 恢复及原有 timing ID/owner 保持、按键可用性测试；
输入恢复增加普通笔两种产品 ID 的 companion guard，确认不禁用 NVT 书写节点。

激光候选修正：使用 MotionEvent 原始显示坐标，PenLaserView 绘制时减窗口屏幕原点；
拒绝非有限/越界位置，悬停退出清空位置并保留窗口，重入更新同一 View，按键释放/
不可用/关闭仍移除窗口。增加 first draw 坐标与窗口尺寸记录，窗口 attach 不再
冒充已显示。录制 Canvas 测试涵盖偏移、横竖尺寸、边界、无位置、退出重入；
这不等于 Android 合成器或用户可见性测试，第六份日志激光根因仍未经实机确认。

直接 APK 候选：Desktop/普通版手写笔应用-v8-20261117/ShengStylus.apk，v8/1.7-test；
构建/平台签名/zipalign/实际 DEX 类及绘制字符串校验，见
reports/ordinary-pen-apk-v8-20261117/apk-build-receipt.json。没有安装器，没有自动安装。
配套原生组件重新编译及 AArch64/依赖检查通过，文件仍为 438652a2 候选；见
reports/ordinary-pen-feedback6-20261117/run-xri2532x/native-3x5cymqm/receipt.json。
没有重新启用已撤回模块；本轮没有刷机、改 USB 平板、生成完整 ROM 或向 E 盘搬数据。

反馈机实际运行原生组件仍 eaf24dc9，新候选未生效，单换 APK 无法替换压感转发服务。
下一阶段要在反馈机安全部署匹配原生组件后验证转发计数、ABS_PRESSURE/MotionEvent
压力变化、激光真实可见性及唤醒/吸附/重连。此前不能标记普通笔修复或完整目标完成。

## 2026-11-17：20:16 第六份日志，截图菜单可用，激光仍不可见

用户反馈能写、截图和菜单正常，但无可见激光指示、无变化压感。不得将能写
当作压感验收通过。Downloads/普通版手写笔故障日志.tar(6).gz，SHA256
1666810e45993850172ba997a6db0d0bdba99e8a81376e7dcf2a7fdd8c604d6e。
分析 reports/ordinary-pen-feedback6-20261117/analysis-summary.json：2029条report5，
压力0..3320、663个值，event7仍仅0/1，应用绘图区压力固定1.2208521E-4，
Pressure forwarded=0 ready=true type=3。实际native PID1308，哈希仍为eaf24dc9，
原测试模块有disable标记，新native未进入实际进程；不能单靠APK声称修复压感。

按键report2有4b/4e/6e。日志明确记录PRIMARY/MENU及SQUEEZE/LASER；20:17:13..17
多次Laser pointer shown，并有对应窗口Surface创建和reportDrawFinished，
但这些仅证实窗口提交，不证明红点对用户可见。可见性/坐标/窗口生命周期根因
尚未确认，不能说用户没按激光键或激光已经正常。先保留已正常的截图和菜单。

包管理元数据仍v5/1.4、product路径且有shengstylus-privapp挂载，但PRIMARY动作
发生在report2收到后约1ms，短按逻辑实际生效。不能只凭缓存版本字段断言新版
代码未运行或要求用户重复安装。后续应采集实际APK哈希与进程/挂载视图再判定。
后续压感需匹配vendor原生组件的安全部署；保持不刷当前USB正常平板、不重新启用
已撤回模块、不用一键安装器、不把原生组件未生效误报为压力数据本身缺失。

## 2026-11-17：19:24 第五份日志，原生服务恢复但压感未转发

Downloads/普通版手写笔故障日志.tar(5).gz，SHA256
1768d3b9dd6bd06773c6311f62c02e6a936a2af01506fedac2d3f8d4dca3c6ad。
分析见 reports/ordinary-pen-feedback5-20261117/analysis-summary.json。
先前测试模块已有 disable 标记，init 服务 running，实际 PID1383；进程、init
命名空间及 vendor 文件均为原始 eaf24dc999e2bbebb1bb0a7467ab692bcb09f88f45f218904c6ff6102c81b452，
不是候选 438652a2。不能重复说本轮仍被 execute_no_trans 阻止运行。
仍有 shengstylus-privapp 模块挂载 APK/权限文件；实际应用仍为 v5/1.4，非 v6。

本轮 HID report5 有3127条，压力0..2833、724种、1580条非零；描述符与已支持普通笔
精确一致。物理 event7 压力仅0/1，绘图区压力固定1.2208521E-4，Java反复记录
Pressure forwarded=0 ready=true type=3。压力已经到达主机，但尚未通过当前原生
链路进入输入事件；不能说笔没有发送压力，也不能把只更新 APK 当作完整修复。

按键31条 report2，包括4b/4e/6e及00，Java usable=true，激光动作实际有日志。
4b短按约90..170ms、4e约142ms，旧版要求380ms长按，故没有 PRIMARY/SECONDARY
动作。候选v7/1.6-test仅对普通笔改为按下触发，重复报告不重触发，Pro保持长按。
增加普通笔边沿/取消/型号切换测试，共97项按键检查通过；APK构建及签名另留回执。
后续交付 Desktop/普通版手写笔应用-v7-20261117/ShengStylus.apk 为实际应用，
不带安装器/Root脚本/原生服务。压感仍需匹配原生组件的安全系统集成和反馈者验收。
不得重新启用已撤回的测试挂载模块，不刷当前USB正常平板，不声称实机已修好。

## 2026-11-17：19:15 普通笔无书写回归，先回退测试模块

新日志 Downloads/普通版手写笔故障日志.tar(4).gz 证明测试模块仍在启用，
native SHA 为 438652a257354e64bb1e2c18415185c87b815d9684bf85855398cd56e4055691。
安装前后 init.svc.vendor.sheng-stylus=restarting，无实际存活服务 PID。
kernel-before/live 与 logcat 都明确显示 cannot execv Permission denied，SELinux
execute_no_trans 拒绝 init 执行 tmpfs 上 vendor_sheng_stylus_exec，进程退出127。
这是先前测试部署引入的回归，不是证明笔坏或新压感逻辑有效。post-fs-data 的
tmpfs 使用 nosuid，可能阻止域转换；未实机确认前不再交付任何模块/安装器。
用户应先在 Root 管理器停用/移除 sheng_ordinary_pen_20261117 模块并重启，恢复
原始 vendor 服务；仅覆盖 APK 不能撤掉该挂载，不得建议关闭 SELinux。
此日志实际系统手写笔应用是 /product/priv-app/ShengStylus、v5/1.4，不是v6，
说明新版应用未实际成为运行版本；不可宣称v6测试通过。

系统智能崩溃也已抓到：com.google.android.as 在注册内容观察者时因缺少 mms-sms
provider 抛 SecurityException，反复出现。与上述 init 执行拒绝是两条不同故障，
应检查 ROM TelephonyProvider/平板包配置，不应清数据、关闭SELinux或直接禁用智能来掩盖。

## 2026-11-17：交付方式最新约束

用户明确不要一键安装器，反馈 v2 安装不上。后续仅交付实际手写笔应用 APK；
不要再将 Root 安装器当作手写笔应用。已单独复制平台签名 org.lineageos.sheng.stylus
versionCode 6 / 1.5-test 至 Desktop/普通版手写笔应用-20261117/ShengStylus.apk，
签名与之前可用的 ordinary-input-fix APK 一致，安装器失败的具体原因仍未知。
单独 APK 不会替换原生压感服务，故不能宣称其包含完整的 native 暂停恢复修复；
底层改动留待后续系统集成，完整 ROM 仍等待普通笔反馈，不应擅自制作或刷入。

## 2026-11-17：普通笔第二轮反馈与 v2 候选

用户补充：压感时好时坏，按键已响应，但两个按钮动作相同、缺激光指示，
另有 Android System Intelligence 屡次停止。不能描述为压感始终不可用或已修复。
新日志 Downloads/普通版手写笔故障日志.tar(2).gz，SHA256
0484aeeaf3cd7d90b4138116e19af181df0c11714af2f4b151bdc5f8998907b1。
报告 reports/ordinary-pen-feedback-20261117/analysis-summary.json：2234 条 report5，
压力 0..7826、785 个不同值；此采集区间物理 event7 仍只有 0/1，未捕获崩溃栈。

发现可测试的状态缺口：native observePanel(false) 可置 suspended_，而 Java
逻辑屏幕仍为 On 时不一定执行 resume。新增 needsResume 和配套 getForwardedCount
返回 -2（仅表示需要恢复，不是计数；-1 仍是无租约）。Java 通过原有门控有序
恢复 mode37/双 timing ID，不自动放开 Off 或重放旧压力包；AIDL 签名/版本未改。
Native 控制器 143 项断言、按钮 84 项断言及 ARM64/平台 APK 编译通过，仍待实机验证。

普通笔 0x6e 不再套用 Pro 握压菜单，候选改为按住显示悬停屏幕光点，松开/息屏/
超时隐藏；不拦截触摸，不是接触屏幕禁写或完整原厂演示协议。Pro 原动作不变。
安装模块进入 init 挂载命名空间再 bind 原生服务；安装器新增重启后实际进程哈希校验。
v2 安装器位于 Desktop/普通版手写笔压感按键测试-v2-20261117/普通版手写笔压感按键测试.apk。
未刷平板、未制作完整 ROM，不能认定普通笔硬件验收通过。

完整日志 APK 1.1：Desktop/手写笔故障日志-20261117/ShengPenCrashLog.apk。
保留原 Root/hidraw/evdev/kmsg 后台采集，增加应用内压感绘图区、前后崩溃缓冲区、
DropBox 崩溃历史、Intelligence 包版本、模块及实际进程/命名空间内二进制哈希。
每轮最多三分钟，可切换绘画应用或息屏复现。无内置 rawdump 亦可采集，但不能
补造未输出的硬锁死异常。未禁用或清除 Intelligence 数据；其根因仍需新增异常栈。

## 2026-11-17：续接后最新状态（取代下文中断时状态）

用户确认当前已能正常开机。ADB 定向 ca10ede3 验证 sys.boot_completed=1，
运行 6.18.39，不能再次从“卡第一屏”重做或覆盖当前可用启动链。
默认 init_boot 不内置 KSU；普通笔先交付测试 APK，待反馈再打完整包。

已将成功开机诊断树的九个内核源码文件合入独立内核仓库，
提交 727b58464（main，已 push）。源码清单 103857 项、Android LTS 2490 项、
硬件源码校验 63 项通过；完整记录 source-merge-verification.json。
合入 task/thread/mm 布局兼容及 rawdump 记录器修复，同步哈希校验链。
.39 current 使用 TPIDRRO_EL0，旧 .32 LKM 使用 SP_EL0；实机成功路径的
精确模块适配仍有必要，不能声称任意未修改的预编译 KSU 模块都能工作。
内核源码及限制见独立仓库 docs/KSU_COMPATIBILITY.zh-CN.md。

新原始日志 Downloads/普通版手写笔故障日志 (1).tar.gz，SHA256
d77f9d2dc4b6b754f8a4f2e7751903eadc7003e62859d6ae23770b05148a420c。
分析 reports/ordinary-pen-raw-20261117/analysis-summary.json：
2025 条 report5（15 字节），pressure 0..2301、459 个不同值，713 条非零；
物理 event7 的 ABS_PRESSURE 仍只有 0/1。report2 有 4b/4e/6e 和 00 释放，
共 74 条；应用观测没有 + 输入。不能再说没有原始压力数据或猜按键码。
普通笔原始 HID 描述符 115 字节，精确匹配后才允许压感转发；保留未知普通
描述符的原有书写路径，不将未知压力布局当作已支持。

已修改 native PenHidEndpoint/PenController 的普通笔压感路径，
PenGattSession 对普通笔也订阅 report5/report2，继续屏幕、归属及 Off 恢复门控。
原生 117 项、按键 84 项检查通过，Android 平台类路径 APK 和 ARM64 服务编译通过。
旧 actor 测试夹具缺少已存在的 Android/快捷键/配对 stub，无法编译；不要记为通过。
测试安装器输出 Desktop/普通版手写笔压感按键测试-20261117/普通版手写笔压感按键测试.apk。
需要 Root；安装服务 APK 并创建独立测试模块，手动重启后通过 post-fs-data
将新原生服务 bind 到原路径，不刷写分区、不需要重打整包。还没有普通笔实机验收。
普通笔改动暂未推送设备树发布仓库，等待测试反馈。

已删除已损坏且被修复分区取代的 product_a.img/odm_a.img 旧备份，
保留其哈希和元数据、本轮正常启动链备份及原始日志。清理记录
reports/storage-cleanup-resumed-20261117.json。本轮没有向 E 盘搬移工作数据。

## 2026-11-17：普通版笔日志、修复包与存储限制

用户已更正：反馈者没有死机，是普通版笔写不了、输入框自动输入 +。
不要再将此例描述成内核 panic。反馈者用上午的 .39 #2、无内置 bootlog。
新日志应用产物在 C:/Users/Dev裴月笙/Desktop/手写笔故障日志-20261117/，
包 org.sheng.pencrash，原生 /dev/kmsg + evdev 同步刷盘，最长180秒。
APK签名与原生/控制脚本在Recovery运行已验证，反馈者已回传有效日志。

日志原件 Downloads/普通版手写笔故障日志.tar.gz；分析在
reports/ordinary-pen-fault-20261117/analysis-summary.json。boot ID前后相同，
native正常退出，无panic/Oops。event14（BT vendor34/product0x4d80）
17.755秒发出14833条KEY_KPPLUS(78)，MSC_SCAN=0x70057，Android
KEYCODE_NUMPAD_ADD=157；大量输入缓冲溢出。真实M80p event7有坐标、
短暂BTN_TOUCH及pressure 1/0，不能将“蓝牙已连”当作可书写验收。

已修源码 PenInputLease.guard 的仅Pro分支以及恢复匹配器；新增
PenInputIdentity，对普通/Pro都按vendor/product/BT地址隔离配件输入，
保留vendor=0的真实NVT节点。身份负例测试通过，ROM平台类路径编译、
R8、平台签名校验通过。候选服务更新 APK 位于
C:/Users/Dev裴月笙/Desktop/普通版手写笔修复-20261117/ShengStylus-ordinary-input-fix.apk。
用户最新实测：普通笔已能书写，但无压感、按键失灵。输入隔离修复有效；不能宣称完整支持。
代码确认普通笔原始压感路径尚未接入，GATT按键报告订阅仅Pro开启。不得直接套用Pro报告格式。
日志APK已增加精确BT vendor34及已知普通/Pro product的只读hidraw采集、原始描述符，
支持连接后每秒发现、2MiB轮转和100ms刷盘；不抓取其他HID设备，不抢占输入。
新APK保持同路径同签名可覆盖安装，需要普通笔分别轻重书写、逐个按键并导出日志。
内核kmi32模块构建和qualification均passed；2026-11-17实机namespace原始ksuinit/KSU加载成功。
revision=ksu39-kmi32-r1/run=7a9e34c56e15fd7d，kernelsu Live，进程标记、sys_enter挂钩初始化完成。
rawdump最终60297ms，无旧ksu_mark_running_process_locked崩溃；PC确认自动Fastboot。
结果reports/ksu-bootloop-20261117/kmi32-namespace-result.json，rawdump在after-kmi32-namespace。
测试后boot/vendor_boot/recovery_a恢复active-before-local；init_boot未改。
配套DLKM已打包并通过AVB hashtree校验，kmi32-dlkm-package.json；474模块（vendor472/system2）。
完整Android KSU早期启动尚未验证，不能宣称已完全修复。
fastbootd可用，但fetch只允许super/vendor_boot。super元数据发现*-cow快照分区；
不得直接写逻辑模块分区或取消快照，先启动原系统检查更新快照/合并状态。

2026-11-17 17:03更新：只读挂载metadata确认其为f2fs，ota/state零字节且snapshots目录空；
super中的旧cow条目不能单独当作活跃更新证据。未取消快照、未擦数据。
用super-metadata.bin+lpdump读取精确extents，备份vendor_dlkm_a和system_dlkm_a，
active-before-local/dlkm-backup.json保存哈希；脚本backup_sheng_dlkm_extents.py。
完整启动试验：KSU run0898fde2700d2ed4，KSU于0.403秒初始化完成进入init.real；
最后rawdump 3204ms。去KSU run8746c1f46aa71028最后2948ms，也未上线AndroidADB。
临时vbmeta flags3对照runa0a3ab5a740878af最后3205ms，未解决。
这几轮电脑最终都检测Fastboot，但没有60秒落盘证明，不能称已证实60秒超时返回。
尚不能把最后出现的rmnet模块当作根因：最后快照可能早于真正故障，需增强后续捕获。
所有boot/init_boot/vendor_boot/recovery/vbmeta及两个DLKM已恢复备份；前五分区设备sha256核对原值。
平板最后在原版Recovery，serial ca10ede3。期间另一台PBAM00/serial b658f72c上线，
仅做了设备身份读取，不能将其ADB上线当作sheng启动成功，绝不对该设备写入。

2026-11-17后续：用户明确要求一直继续，目标普通版笔（含压感/专属按键）及完整KSU支持；
已建立active goal。logger-r2加入独立sheng-log线程和kernel_restart入口同步最终快照，
Module.symvers逐字节SHA不变，源码provenance/补丁校验已更新，不跳过源码校验。
实机r2 run0d571a9700e0b012成功抓到真正退出原因：system/system_ext可挂载ext4，
product既无有效erofs也无有效ext4，InitFatalReboot signal6，pid1在3.380472秒请求bootloader。
此前约3秒日志中断是最终重启消息没来得及落盘，不是已证明卡在rmnet加载。
product_a/odm_a均从super精确extents流式备份到active-before-local；各自*-backup.json，
含device_sha256_verified=true。product首部是随机代码样式，无文件系统magic；
odm首部虽然有ext4magic，但块数对应约2.67GB，超过其1.14GB分区。
备份时C盘一度耗尽导致ADB流被截断，未写设备；恢复空间后续传，并对全备份和设备SHA核验成功。
已用NTFS透明压缩本轮reports及LZX product备份；不删除数据、不用E，现约4.8GB可用。
正在fastbootd用out-clean-ota-20261116同版已AVB验证的product.img/odm.img修复相应_a分区。
product刷写已成功；odm刷写进行中。不能再把损坏的product/odm恢复作为正常启动基线。
当前DLKM仍为候选KMI32匹配模块；boot/init_boot/vendor_boot/recovery暂恢复原版等待下轮log2测试。
stock BluetoothExtension只读选类反汇编在reports/ordinary-pen-fault-20261117/stock-protocol-review，
原始APK路径和哈希记在provenance.json；普通笔原始HID日志仍待反馈，不得猜Pro布局。

用户禁止使用 E 盘（机械盘太慢），本轮新产物和工作目录只用 C/WSL。
此前Gradle缓存搬移已停止，已搬出的文件恢复到C，原路径非junction。
正常boot/init_boot/vendor_boot/recovery/vbmeta的本轮备份已从设备读取到
reports/ksu-bootloop-20261117/active-before-local/，哈希逐项通过。
不要为后续试验依赖 E 上旧备份。

KSU模块重建曾因诊断源码位置不满足QTI相对路径失败；已将common实际
移动到 ksu-rawdump-20261117/vendor-kmi32/k618/ws/common，旧D/common
保留为同盘别名，未复制第二份树。build_sheng_ksu_kmi32_modules.py已改为
检查真实目录拓扑，并在模块结束后生成匹配Image；需读取构建receipt的最新
状态。ABI CRC检查应使用当前 Module.symvers；vmlinux.symvers时间戳旧，
不能将这个旧文件当作当前候选的CRC结果。

## 2026-11-17：原 ksuinit 实机复现到具体布局错误

通过独立 PID/mount namespace + chroot，运行从 init_boot_b 提取的原
ksuinit 和 kernelsu.ko；namespace 内 PID=1，host /init 不变，先让 Recovery
和 rawdump 正常工作。launcher 位于 reports/ksu-bootloop-20261117/namespace-loader/。
直接 insmod 的符号错误不代表这条真实加载路径；原 ksuinit 成功进入模块 init。

rawdump run=90a4ccb73d5c1601，6.719 秒发生 Oops。PC 为
ksu_mark_running_process_locked+0x78，故障地址 0x318，x24=0。
同一模块反汇编：先 ldr x24,[init_task+0x648]（tasks 偏移1608），
再 ldr x8,[x24+0x318]。本地 .32 的 tasks=1608，.39 的 tasks=1736，
模块因此读错字段并解引用空指针。证据见 namespace-ksu39-fault/ 和
ksu-layout-fault-evidence.json。这是实际可复现的 .32/.39 布局回归，
修复后的完整修补启动仍需再验收。

隔离诊断树 /root/sheng-pixelos/diagnostics/ksu-rawdump-20261117/common
已按本地 .32 恢复 thread_info 与 task_struct 声明，保留 .39 kstack_offset
到原保留槽；同时恢复 vlag/vprot union 配套的两段 reweight 逻辑，并把
mm_struct 的新增状态放入原保留槽。fork.o 的 DWARF 已确认 tasks/mm/pid/
thread_node/cred/signal 偏移和 task_struct 大小恢复 .32。完整内核和板级模块
仍需等 kmi32-candidate-build.json、kmi32-module-build.json 明确通过。
不要把目标文件布局通过写成已完成实机修复；不要将候选内核和旧 .39 模块混刷。

板级模块隔离目录 vendor-kmi32 与 project-kmi32 已复制，不覆盖正式构建；
其额外诊断改动有完整固定哈希与 patch，android_lts_contract 和
android_source_contract 均已通过。正式源码树、发布包尚未固化本项修复。

## 2026-11-17：KSU 诊断续接（14:11）

相机方向、默认全屏、微信显示已修好，当前任务仅继续 .39 修补 KSU
卡第一屏的回归，不要重新处理已验收事项。

实机 bootloader 将 A/B 两槽标记为 unbootable；set_active a 后，正常
Recovery 可启动。recovery_a 镜像内 kernel 为空，此设备 Recovery 从 boot
取内核。不要往 Recovery 里额外塞内核：该试包被引导器拒绝，尚未进入内核。
已恢复 active-before/recovery_a.img。临时 fastboot boot 原 Recovery 也曾
返回 Bad Buffer Size，不要将其解释为 KSU 或内核崩溃。

已验证 diagnostic60/boot.img + 未修补 init_boot_a + 原 Recovery 能正常
进入 ADB。revision=ksu-39-rec60b；rawdump run=bfc75c7ed3c9f74c，
在 uptime 60.087499 秒记录 TEST_RETURN_BOOTLOADER timeout=60 fault=0，
随后用户和电脑均确认返回 Fastboot。恢复正常 boot_a 后已重新进入 Recovery。
日志位于 reports/ksu-bootloop-20261117/manual-ksu-rec60-final/。

在此 Recovery 直接 insmod 从 init_boot_b 提取的 .32 kernelsu.ko 返回 1，
日志包含缺少符号及 prepare_creds 命名空间不匹配；未产生 panic。
直接 insmod 没经过修补镜像的 ksuinit（该程序含 kallsyms 与模块修改逻辑），
不能用此结果解释早期启动卡死。本地 .32/.39 的 prepare_creds 命名空间
相同，因此这个手动加载错误也不能当作 .39 独有回归。

首次补抓 after-firstscreen-resumed 中仍是昨日 ext-raw-1116m 日志，
不是此前第一屏失败记录。当前还没有抓到修补启动路径本身的有效失败日志。

## 2026-11-17：KSU 回归与诊断时限

用户确认此前 6.18.32 可以正常修补、开机并使用 KSU。排查当前 6.18.39
回归时，以这份已验证的本地 .32 构建为基线，比较实际源码、配置和 ABI；
用户明确要求不要继续通过对比官方 KSU 模块来判断问题。

本轮已从两份本地 vmlinux 验证 task_struct.cred 偏移由 2312 变成 2440，
thread_info 大小由 48 变成 64；从实机修补镜像提取的 KSU 模块标记为
6.18.32。保留实际 rawdump 与加载结果，不能仅凭这些差异声称根因已验证。

用户将后续诊断自动返回 Fastboot 的等待时间改为 **60 秒**。本条取代
下面 2026-11-16 的 180 秒默认值。2026-11-17 第一轮设置 180 秒，但在
启动约 288 秒时仍停第一屏且 USB 未枚举，自动返回未生效，用户手动进入
Fastboot。继续参考已验证的 rawdump（288..290 MiB）记录器，不依赖
pstore／last_kmsg；若失败早于 UFS 注册，应先让记录器有可写分区，再复现。

## 2026-11-16：诊断启动超时按实际进度调整

用户将本轮诊断自动返回 Fastboot 的等待时间从 60 秒改为 180 秒，并授权
后续遇到类似情况时根据日志及初始化进度酌情延长，无需逐次确认。记录每轮
实际内核参数、启动进度和返回原因；不能用延长时间代替修复已经确认的错误。
保留 rawdump 日志及单轮返回 Fastboot 的诊断设计。确认正常进入系统后移除
诊断超时；进入 Recovery 抓日志前先刷回已验证可启动的 boot 配套链。
Recovery 默认 ADB 保留，使用用户指定的最新源码包和外置 DLKM 模块方案。

## LineageOS 与 PixelOS 的共同维护要求

用户要求设备树同时适配 LineageOS（LOS）和 PixelOS。6.18 的内核、模块分区、
perfconfigs、低功耗及硬件修复必须由共用设备配置消费，不能只接入某个 ROM
产品。各自保留产品入口和默认系统应用；公共源码保持对应 ROM 清单指定的内容。
两种 ROM 使用独立源码及输出目录，分别记录完整构建、VINTF、实机启动和
硬件／功耗验证；一边通过不能代替另一边验收。

## 2026-11-11：人脸识别必须接入系统原生接口

用户明确要求：不要通过单独的设置入口注入接入人脸识别，要使用系统原生
人脸接口和正常的录入／解锁位置。此前 r42 的 TrustAgent 方案虽然已安装并
通过无摄像头引擎检查，但不是用户要求的原生 Face 生物识别流程；不能把它
或设置入口覆盖算成任务完成。后续优先接入 IFace／ISession 和系统原生
Settings、Keyguard；保留原版 SystemUI 和 manifest 固定的公共源码。

已验收的识别引擎、镜像／框跟踪、靠近镜头的录入提示，以及严格大于 0.5 的
候选判定要求继续保留。普通软件人脸识别按非强等级处理，不能生成或伪造
有效 HardwareAuthToken，不能声称可用于强生物识别或支付。录入凭据、取消、
锁定、重启首次解锁及摄像头隐私限制仍需通过原生链路验证。

## 2026-11-10：5.15 vendor 迁移到 6.18 的性能与低功耗配置

用户提醒：当前底子 vendor 是从基于 **5.15** 的系统提取的，最开始的原厂
底子已经出现过 **qcom-lpm 失效**，相关 perfconfigs 需要适配。原厂配置不能
直接作为正确的功耗基线。迁移到 **6.18** 时必须主动深度核对 **perfconfigs
及相关 Qualcomm 性能、功耗配置**，不能等到功耗异常才检查，也不能只替换
内核或确认模块已加载，就认为这部分已经兼容。

具体要求：

- 核对 vendor/odm 中实际使用的 perfconfigs、性能 hint/profile、qcom-lpm
  及相关服务／库，查清它们依赖的 5.15 节点、接口、拓扑和状态通知。
- 与同一批 6.18 内核、模块的实际导出逐项对照，检查节点路径、权限、
  CPU／集群和频率映射、调度及低功耗接口、返回值和事件是否兼容。
- 同时保留原厂 5.15 配置和当前已验证 5.15 运行状态作对照，区分原厂遗留
  故障与 6.18 迁移问题。检查 post-boot 是否完整执行、调速器是否正常选择、
  性能提示结束后频率与 latency QoS 是否释放，以及深度空闲驻留是否增长。
- 将确认需要的配置调整、节点／接口适配以及 init／SELinux 配套修复
  固化到设备树，保留 5.15 对照和修改前后的依据。相关根因需要实测定位，
  不能把“优先排查 perfconfigs”写成已验证的具体故障结论。
- 用真实场景验证性能 hint 是否生效、负载和状态感知是否更新，以及
  息屏、待机、唤醒和功耗是否正常；服务启动、模块加载或一次编译成功
  不能替代这些验证。
- 不通过关闭低功耗、永久锁最高频率、伪造状态／成功返回值来清掉故障。

本项属于 [6.18 Android 分区集成](KERNEL618_ANDROID_INTEGRATION.md) 的
必查项，尚未在当前 Android 设备树中完成迁移与验收。
