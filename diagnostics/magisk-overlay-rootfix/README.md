# Magisk / overlay 交接修复

## 当前验收：Native05（2026-11-21）

- 同一套内核和模块：Magisk 两次独立 Android 启动、KernelSU LKM 32680 一次，均有真实 `/system` overlay、`init_exec` 和 SELinux Enforcing。三个启动均返回 Recovery，保留的 rawdump 2 MiB 区域未变。
- 两种 root 方式配用各自的 `init_boot_b` 和 `vbmeta_b`，不混刷；历史 KSU 备份不适用于 Native05。KSU 的已存配置开启了 ADB Root，普通应用独立授权未测。
- 最初报 `getfilecon` 的是策略加载前的 Android `libfs_mgr`。已复现的是未移走的文件 bind 被父 overlay 遮住；历史 SELinux hook 本身未跟踪。当前候选不关闭 `/system` overlay 或 SELinux。只读保留的历史原始日志与后来成功启动的 rawdump 是两份不同证据。
- Native05 运行证据见仓库根目录 `reports/sheng-magisk-real-overlay-20261121a/native05-runtime-acceptance.json`。USB 3.0 物理重插与重插后重新开启 MTP 的文件往返通过；MTP 保持开启跨重插、USB 主机角色、键盘拆装和外接 DP 仍待实机验收。

以下带日期的段落是历史记录，其设备状态和待测项不代表当前状态。

## 2026-11-21 真实 overlay 前置审计（最新，尚未通过原故障条件）

累计五次不同 Android 启动均完成并稳定观察 90 秒，Magisk root / Enforcing
正常；仍均不是 /system overlay 验收。USB sysfs 实测 super-speed、device
角色，内部显示可由 SurfaceFlinger 查询；没有冒充 MTP 压力验收。

正常构建源码仍遗留的两处 /system overlay=off 已移除，AVB 等其他字段
不变；13 项源码/解析测试及六个真实 fstab Ninja 复制边通过。仅源码和
staging 更新，未刷分区。只读私有命名空间审计发现旧 scratch 中五个
vendor/ODM upper 文件均不同于当前运行 lower，内容已备份至 E 盘；原
scratch 未修改、删除或启用，完整 xattr 仍保留在原处而非全部进入 tar。
开启前必须先安全处理这些过期覆盖文件，不能直接激活旧显示服务/库。

当前 b 槽 root Recovery，启动分区、内核、super 和 rawdump 复核一致。
真实 /system overlay 原故障条件及该条件下重复启动、KSU 回退仍待验收。
详见 `reports/sheng-magisk-overlay-acceptance-20261121a/STATUS.md` 和
`preflight-qualification.json`。旧版清理未执行。

## 2026-11-21 Dolby 修复后的实机续测（当前状态，优先于下方历史记录）

已从当前设备树完整编译 Dolby APK（定向 javac/D8 构建，不冒充完整 Soong
产品重编译），版本 52/3.0.3，包含 DolbyTileService。仅更新 product_b 和
匹配的 vbmeta_system_b，完整 AVB/负向测试、文件系统差异审计及实机读回通过；
没有清数据、禁用 Dolby/RescueParty、放宽 SELinux、切槽或改公共源码。

一次正常 Android 启动完成后稳定观察 90 秒，前后实测 Magisk 31.1 root、
magisk 域和全局 Enforcing。有效运行 APK 的路径、版本及 SHA 与新构建一致，
本次观察未再出现缺类崩溃/RescueParty 重启。随后主动回到 Recovery，内核
build ID、343 个模块文件、启动分区和 rawdump 均复核通过。唯一 KSU 回退
文件仍保留并复核哈希，但新组合的回退启动尚未验收。

**仍未覆盖真实 /system overlay 的原故障条件、重复启动及 KSU 回退；不是
Magisk 根治全部完成。** 当前 b 槽 root Recovery。旧版清理仍延后未执行。
详见 `reports/sheng-dolby-source-repair-20261121a/STATUS.md`，尤其
`completion01/qualification.json`；原 CRLF 解析误判记录保留，已在同批
既有证据上只读复核，没有为修解析器额外启动 Android。

## 2026-11-21 Android 验收续测（最新）

已通过 `/debug_ramdisk/magisk su` 实测 uid=0、magisk 域和全局 Enforcing；
裸 su/magisk 不在 shell PATH，先前该命令失败不能作为 Magisk 未加载的证据。
但 Android 尚未完成稳定启动。持续 logcat/内核流抓到 DolbyTileService 缺类
连续崩溃，RescueParty 由 system_server 明确请求 reboot,RescueParty。
已回到 b 槽 Recovery，未刷新镜像、清数据或关闭 SELinux/overlay。
首次循环耗尽 b 槽重试资格后曾用标准 set_active b 重置当前同槽资格，
随即只进入 Recovery，未切到 a、未将失败启动标记 successful。

当前源码含该 Dolby 类，但物理 product 备份 APK 不含该类或对应声明；
有效运行 APK/包扫描缓存/重复位置仍需进一步核对，不能用物理备份替代
Android 合成视图。新增 APK 源码声明/编译声明/真实 DEX class_defs 门禁，
5 项测试通过且旧 APK 被拒绝；新 APK 尚未重建部署。
此外捕获的 Android 没有真实 /system overlay，故仍未验证原失败条件，
不能将本次 root/Enforcing 局部通过记为 Magisk 根治完成。
详见 `reports/sheng-magisk-android-imagefinal-20261121a/STATUS.md`。

## 2026-11-21 已部署状态（优先于下方历史记录）

candidate04 的十个分区已通过实际 fastbootd 部署及完整 SHA-256 读回。
vendor_dlkm 使用标准逻辑分区接口增加 237,568 字节，未写 raw super，
未切槽或清数据。首次新 Recovery 验收发现模块阶段重链接 vmlinux 后，
旧 Image 未重新生成，实机出现 BTF mismatch；该组合未获运行验收。

设备树构建入口现于模块构建后重新执行保存的 Kbuild objcopy 配方，
逐字节核对 Image 与最终 vmlinux，核对 split-BTF base、配置及符号表，
在 OTA 准备、安装和 boot 打包时阻止旧 Image。旧镜像及 receipt 均保留。
9 项真实 LLVM 夹具测试通过，实际旧 Image 被新门禁拒绝；474 个模块
重新通过签名/BTF/CRC 校验且内容不变。新 boot 与对应 vbmeta 的完整
离线 AVB 链及旧 boot 混用负向测试通过，root flags 保持 0。

随后仅更新 boot_b、vbmeta_b，六个启动类分区完整读回符合预期，super
元数据及旧 rawdump 不变。一次真实重启进入 Recovery，运行内核 build ID
为 `29323b3b52a304fc24b0ccfab73a3cdf30224aeb`，343 个模块文件及已加载
build ID 均匹配，BTF mismatch 消失，rawdump 仍保留。
报告：`reports/sheng-magisk-image-consistency-20261121a/`，最终实机证据为
`recovery01/readonly-completion.json`；原日志检查误匹配 ramoops/debug
名称的失败记录保留，修正解析后只读复验，没有额外重启。

**尚未验证本组合的 Android Enforcing、真实 /system overlay、Magisk root、
重复启动及 KSU 回退；不得将 Recovery 配套验证记为 Magisk 修复完成。**

## 全源码构建与新离线镜像进度（优先于下面历史状态）

当前实际产品 source-built init/remounter、全内核与匹配模块已完成编译和
来源/ABI/BTF/签名审计。新 boot-family01 的四张启动类镜像、remounter01 的
system/system_ext 与 vendor_dlkm/system_dlkm 新叶镜像均完成各自离线校验，尚未部署。
详见工作区 `reports/sheng-magisk-fullsource-package-20261120a/STATUS.md`。

2026-11-21：两级完整新 AVB 链已通过精确配套镜像的离线校验，root flags=0，
原 root 公钥、child 链公钥及非哈希描述符保持；损坏签名、错误密钥及篡改 boot
数据的三项负向验证也均被正式 avbtool 拒绝。报告位于工作区
`reports/sheng-magisk-fullsource-chain-20261120b/STATUS.md`。

动态分区部署与实机验收仍未完成。新 vendor_dlkm
比当前逻辑分区大 237,568 字节；不得直接按旧分区大小刷入，也不能省略 FEC、
签名或模块来规避容量问题。旧 image-trial03 不代表本轮新源码镜像。

现有 COW 分区全部按占用计入后，物理空隙与分组容量足够增长；这不是 liblp
调整或 fastbootd 刷写通过证据。后续正式host liblp容量模拟、以及按公共源码
对fastbootd清UPDATED/同步两槽的离线最终表模型已通过，保留全部旧映射/COW。
详见工作区 `reports/sheng-magisk-liblp-growth-20261121a/STATUS.md`；实际fastbootd
HAL槽数、写入、回退及Android启动仍未验收。super header的bit1按源码是
OVERLAYS_ACTIVE，模型保留该位，没有关闭真实overlay绕开问题。
当前启动重新采集的 metadata 与历史审计哈希
不同，已重新检查 OTA state 为空且没有快照状态文件，但 Android 实际合成
映射仍未验证，不据此授权 raw super 写入。

后续一轮真实fastbootd暖切getvar预检已确认两槽、b槽、已解锁、快照none、
容量及256MiB下载上限，并在同bootID返回Recovery；没有扩容或刷写。两张大
ext4候选已通过正式sparse转换/还原及独立展开SHA校验。见工作区
`reports/sheng-magisk-fastbootd-preflight-20261121a/STATUS.md`。实际传输、部署、
回退和新组合Android/Recovery验收仍待完成。

离线 EROFS 标签通过读取镜像原始 inode/xattr 保留，不依赖 WSL 支持设置
`security.selinux`，没有跳过目标镜像标签校验或伪造 init 标签。新增工具与
元数据读取器只用于离线打包，不接触设备。Magisk 完整启动验收仍未完成。

## 2026-11-20 最新状态（优先于下方历史研究记录）

隔离 fs_mgr/init 与内核候选已经打包并实机测试；真实 `/system` overlay
启动仍失败，不能记为根治完成。最新限时取证运行 `43688be29d73ba3c`
直接抓到 `/system` overlay 下三个 Magisk rc 文件绑定，普通卸载因此 EBUSY，
随后 PID 1 exit 127。原 preserve-rawdump boot 已恢复，设备在 `_b` Recovery。

设备树 `interfaces/compat/overlay-remounter/` 已新增保留子挂载的重挂载候选，
完成 Android 静态链接及 Recovery 独立命名空间九类真实 syscall 测试。
设备树和 WSL 镜像的 debug 产品选择及私有策略目录已经接入，并通过实际
`custom_sheng-userdebug` 的 dumpvars 检查；这不是完整 Soong 构建图或安装验收。
联合策略编译、neverallow 和完整文件标签库的五个路径查找通过。
尚未刷入新 remounter，Enforcing Android 启动验收仍待完成。
详见 `reports/sheng-magisk-busytrace-20261120d/result.json` 及该候选 README。

内核挂载修复现已接入实际 `kernel/xiaomi/sheng` 源码及完整来源清单；原有
2490 项 Android LTS 固定源码检查保留，并追加修复补丁/来源记录的固定哈希。
正式产品保存的编译参数已用于单独编译该源码，25 个导出符号 CRC 与基线
一致，原对象、配置和 Image 未改。见
`reports/sheng-magisk-kernel-source-integration-20261120a/`。
这不代表完整内核/模块重建或实机验收。
fs_mgr 和 first-stage init 已新增 sheng 自有源码变体，最新锁含 143 个固定上游输入、
116 份本地源码/头文件/NOTICE 中只有一份 fs_mgr 实现含已评审差异；保留公共
defaults 与依赖。24 个 C++ 文件使用正式产品保留的编译边完成隔离编译，
first-stage init 链接通过。debug 产品 dumpvars 选中该 init 与自有 remounter；
真实 GNU Make 门禁的正向/漂移拒绝测试通过。见
`reports/sheng-magisk-source-variants-20261120a/`。这不是重新生成的完整 Soong
图、安装覆盖或实机验收；旧 AVB 链校验不自动覆盖此新 init 的后续打包。
随后源码依赖核查发现原 libsnapshot_init 会间接带回公共 libfs_mgr，已声明
保留原 snapshot 实现和 defaults 的自有依赖变体，改为引用修复库；该新增
variant 的独立编译及完整图验证仍待完成，不由上述 24 文件编译结果代替。
remounter 的隔离 Soong 分析尚未通过；失败/手动停止日志保留于
`reports/sheng-magisk-remounter-soong-20261120a/`、`...20261120b/`。

### AVB 与快照补充核查

实机 root vbmeta 的签名结构有效，但 Flags=3，且其中 boot/init_boot/
recovery/vendor_boot 四个 hash descriptor 与实机对应内容不匹配；dtbo 匹配。
不能仅将 Flags 改为 0，也不能把此状态下开机成功视为验证链通过。
已从两份设备树 BoardConfig 移除默认 `--flags 3`，实际产品 dumpvars
确认不再强制关闭验证；实机 vbmeta 未改。
证据：`reports/sheng-magisk-remounter-integration-20261120a/avb-parents/`。

`reports/sheng-magisk-captured-avb-chain-20261120b/qualification.json` 已完成
完整候选链的离线校验：十个实机配套分区读入 RAM，与设备逐一核对哈希，
结合 image-trial03 的 system/system_ext/vbmeta_system，生成同密钥 Flags=0
根候选，更新四个过期 boot 类描述符。根签名、签名内的子链密钥及各层
hash/hashtree 均通过本地正式 avbtool；结尾复核设备哈希、metadata 和 boot ID。
本地 avbtool 会向递归子链继续传入根 PEM，因此改为两级分别指定各自密钥，
并严格核对子 PEM 与根签名内的链密钥一致；没有跳过任何一层的数据校验。
42 项回归通过，其中五项使用真实 avbtool 的合成镜像验证正确密钥通过、
错误根密钥/子密钥/链密钥和篡改数据被拒绝。失败的 a 轮证据原样保留。
这不是设备 AVB、OEM 信任根、完整 Soong 构建或 Android 启动验收；实机仍
Flags=3，未刷写、重启、切槽或清数据。根候选不能单独刷入，更不能据此回锁。

只读获取的 metadata 在离线副本中检查：ota/state 为空（默认 None），
ota/snapshots 无逐分区状态文件，无其他 OTA 指示文件。COW 分区仍在，
但不能据此推断活动快照。未挂载或修改实机 metadata，也未授权 raw super
写入。host dump.f2fs 会调整镜像的 superblock 几何字段；提取时仅让它操作
可丢弃的 RAM 副本，保留原始采集及其哈希。Android 实际映射仍待验证。
证据：`reports/sheng-magisk-snapshot-audit-20261120a/`。

Pro 手写笔按用户要求排除，不纳入本轮整改或完成条件。

## 历史研究记录（下述“尚未部署”等描述对应早期阶段）

这是隔离研究候选，不是已完成修复，不接入默认构建或刷写脚本。
用户已要求先修 Magisk，其他问题暂不推进。不得把 `overlay=off`、删除
scratch、改用另一个 Magisk 交接分支、伪造标签或关闭 SELinux 当最终修复。

## 已定位的分层问题

| 项目 | 当前证据 | 本目录的处理 | 完成情况 |
| --- | --- | --- | --- |
| `/system` 的 `overlay=off` | 已部署 first-stage fstab；此前是规避，不是标签/挂载根治 | 保留当前可启动环境用于回退；根治验收后才能撤掉 | 临时规避仍在，未根治 |
| 缺少 context 就不保护子挂载，仍给父目录加 overlay | 历史 ENODATA 日志、实际 fs_mgr 函数的隔离复现 | 仅对 ENODATA/EOPNOTSUPP 接受真实的“无标签”状态；不合成标签，移动保留原 inode；其他读取错误使该次操作失败 | 隔离候选通过，Android 早期策略环境未验收 |
| 所有子挂载都用目录作为 MS_MOVE 目标 | 实机独立命名空间中，文件→目录报 EINVAL；原函数即使报错仍挂 overlay 并遮住 init | 文件挂载使用文件占位，目录挂载使用目录占位 | 实际候选函数的主机回归通过 |
| 一个子挂载保护失败，父 overlay 仍继续挂载 | 原函数故障注入可复现 | 失败则不发布父 overlay，并恢复已移出的子挂载；不是最终正常路径下禁用 overlay | 负向回归通过；完整 Android 策略未验收 |
| 已删除绑定源的 MS_MOVE 报 ENOENT | 实机 kretprobe：目标 get_mountpoint=0，attach_recursive_mnt 内的源根 get_mountpoint=-2 | 内核候选只在目的端可能有叠层/传播时预分配源根 mountpoint；不删除目的端检查、权限检查或 d_unlinked 检查 | aarch64 namespace.o 编译通过，新内核尚未运行 |
| 旧 fstab 回归测试强制 overlay=off | 原测试保证的是临时规避不丢失 | 不再用该测试通过证明根治；以允许 overlay 且 init 绑定仍可见的回归替代根治验收标准 | 根治门禁已区分，旧产品仍保留规避 |

## 补丁边界

- `fs_mgr-preserve-file-submounts.patch`：针对公共 fs_mgr 的待评审候选。
  只在 `/tmp` 副本应用和编译；公共仓库仍是干净的 65789bc4。此前“不改公共
  仓库”的边界没有被静默取消。正式集成此补丁需先解决源码所有权范围。
- `kernel-avoid-unused-source-root-mountpoint.patch`：针对保留内核 namespace.c
  的候选。私有、空的目的挂载点没有需要移动到源顶部的旧挂载，不应为这个
  不会用到的占位拒绝已有的、绑定源已删除的挂载。共享或已占用目的地继续
  走原检查。尚需运行时覆盖共享传播、叠层和失效路径；编译成功不是证明。
- 不修改 SELinux 钩子返回值、不伪造 context、不放宽策略。
- 两个补丁必须联合验证。只有 fs_mgr 候选时，已删除源仍会被当前内核拒绝；
  主机测试对此检查的是安全失败、原绑定不丢失，不是把它记为根治成功。

## 验证与复现

`test_candidate.py --fs-mgr /绝对路径/fs_mgr_overlayfs_mount.cpp --out /新文件.json`
在 Linux root 下运行：从受 SHA256 约束的实际源文件抽取原函数与候选函数，
编译并在独立、private mount namespace 执行真实 tmpfs/bind/overlay/MS_MOVE。
SELinux context 成功/错误边界使用明确的 shim；真实 ENODATA 来自主机 xattr。
这不是 Android 预策略 SELinux 的仿真。测试结束检查调用方 mountinfo 不变。

`compile_objects.py` 使用保留的准确 kernel savedcmd 和 Android ramdisk
Ninja 编译规则/flags，仅编译两个隔离对象；不替换原源文件、原对象或 init。
参数见 `--help`。它不链接内核/Android init，不产生可刷镜像，不访问平板。

详见工作区 `reports/sheng-magisk-rootfix-investigation-20261120/`：
14 项主机用例（含 2 项原函数错误行为复现）、实机挂载对照、实机 PID 过滤
kretprobe、2 个目标对象编译及最终清理检查。探针只在专用实例启用，结束后
均移除，原 tracing 控制和调用方挂载表核对相同。没有重启、刷写或切槽。

## 不能省略的根治验收

1. 解决公共源码改动的所有权限制，评审并集成两个候选，而不是自动打公共补丁。
2. 验证内核候选下已删除源的移动成功，并补齐共享/叠层场景。
3. 生成匹配的新内核/模块与 first-stage init；AVB/回退文件校验后按授权范围部署。
4. **移除 overlay=off，保留真实 /system overlay 条件**：确认 ENODATA 场景不再
   丢失临时 init 绑定、Magisk second-stage 正常、Root/Enforcing 正常。
5. 验证非 Magisk 启动、Recovery、KSU 回退与原用户数据不受影响。

上述门禁尚未全部满足，不得标记“根治完成”。
