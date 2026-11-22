# Recovery 固件与 UI 的正常构建集成（2026-11-13）

当前安装基线仍为 Android r64、独立 Recovery r59。这次处理正常产品构建的
固件初始化与 UI 输入，不将它记作新 Recovery 镜像或完整产品验收。

## 已确认的构建缺口

`prepare_sheng_pen_settings_product.py --include-recovery` 原先只同步 UI、
日志模块脚本和模块清单，遗漏 r54 的 firmware-path 类型与权限、硬件启动脚本，
以及后续 standalone 源文件。构建树已有新的 genfs 标签却没有对应类型定义。
全树镜像报告和针对 Recovery 的逐文件检查确认了这些差异。

正常产品注册的是 `rootdir/etc/init.recovery.qcom.rc`。它仍通过旧的
`/sys/kernel/boot_adsp/boot` 触发器启动 ADSP，没有设置已验证必需的
`/sys/module/firmware_class/parameters/path`，也没有使用 r59 的固件完整性检查。
仅同步 standalone 的 `init.recovery.sheng.rc` 不会改变这个正常入口。

## 修正

正常 qcom Recovery 入口现在在 early-init 尝试挂载固件，在 fs 再次尝试，
设置精确 firmware-class 路径，再启动同一个 `sheng-recovery-hardware`
oneshot 服务。该脚本检查 adsp.mdt/adsp.b01，并只启动 offline 的 ADSP。
正常产品清单补上脚本安装项，保留原 USB 与 fastbootd 固件卸载流程。

同步工具带上完整 `rootdir/recovery`、正常 qcom RC、file.te/init.te/genfs_contexts
和模块清单；旧的两文件产品复制块可精确升级，其他已有产品输入保留。
未知复制块或重复硬件脚本目标会报错。构建后的镜像检查覆盖同一组输入。
既有 Recovery 专用权限原样沿用，没有新增 Android allow 规则。

4 项临时构建树回归检查覆盖缺失/旧输入恢复与备份、重复运行、CRLF 产品文件、
未知复制块和重复目标拒绝；此前 4 项手写笔源码同步回归也通过。
qcom、standalone、late-modules 的 init 语法及 shell 语法已检查。
Recovery 源码镜像检查为 16 个输入、0 个差异。

## 正常构建与产物验证

构建入口：`tools/build_sheng_pen_settings_product.sh`。本批目标为
`librecovery_ui_ext`、`sepolicy.recovery`、`vendor_sepolicy.cil`、
`init.recovery.qcom.rc`，以及 Recovery 的硬件脚本和日志模块脚本/RC 安装路径。

正常构建于 16:41 完成，编译阶段耗时 13 分 38 秒，1,450 项步骤全部通过；
构建前后公共源码审计通过，构建后 31 项源码镜像检查为 0 个差异。
16:42 产物检查完成：脚本/RC 与源码字节一致，UI 实际链接设备库并导出
`make_device`，7 个直接依赖均有对应 Recovery 输出。编译后的策略查找与
访问决策通过，10 个既有 permissive 域保持，普通 vendor CIL 不含固件专用类型。
实际 secilc 构建命令未使用 `-N`，neverallow 检查保持启用。

| 正常构建产物 | SHA-256 |
| --- | --- |
| librecovery_ui_ext.so | `f98b3fcbbea7a8fa23f2758eda0386df5017e0f95701c4a06a14612ea7cf910c` |
| Recovery sepolicy | `26a5bd2b1671dc0ad5c8a7abc72e68597c238e5d34ccd4556f294138d91d85d0` |

成功回执为 WSL `hardware-diagnostics/sheng-pen-settings-20261112/`
下的 `modules-20261113-082702-4IApxH/status.json`。
工作区证据位于 `reports/device/20261113-full-product/`：
`recovery-regressions.json`、`recovery-source-mirror.json` 和
`recovery-validation/verification.json`，后者目录保留构建回执、源码审计、
实际策略检查和 UI 构建命令。旧的未修复策略被检查器正确拒绝。
本批没有打包或安装镜像，当前系统和 Recovery 的安装验收状态不变。

产物检查器为 `tools/verify_sheng_recovery_product.py`，要求完整成功回执及源码
镜像检查，再检查实际安装输出、UI factory 导出和设备 UI 库链接、直接依赖、
编译策略的 genfs 查找和访问决策。`check_sheng_recovery_policy.c` 验证 init
可打开/写入精确固件路径、相邻泛化 sysfs 仍不可写，以及 recovery 可读取。
还对比已验收策略的 permissive 域集合，并要求普通 vendor CIL 不含专用类型。

## 参考与范围

本次重新 fetch 并检查：piano seventeen
`8c0bb4b9d15ea349eaa09d6de0aa4fec43f7ff41`；nuwa lineage-24.0
`8e2b6ca4375919035587115189760eed64f14b8d`；sm8550-common
`62f4b9c1d20c88f02e0bc7f1b2c932bd5c750eb1`。
piano 使用不含内核的 Recovery 和自己的触摸固件复制项；common 的旧 ADSP
触发器与本设备原正常入口相同，不能代替 sheng 已验证的精确固件路径修正。
没有复制这些设备的板级数值、内核、固件或应用。

公共 Recovery 固定为 `c1ccd0b4a17557f97ed864b96f160674609c1c54`，
system/core 为 `65d661b1a536701e8b118be4e9728d7b5ca727c9`，
system/sepolicy 为 `d61fd80832f558d52de026097d30d695634e8b0f`。
此 init 在没有并行加载参数时默认 `LoadParallelMode::NONE`；正常构建没有
standalone bootconfig 文件不能单独证明它会并行加载。该文件现已同步供
standalone 工具使用，没有为了复制 standalone 布局而改变普通 Android bootconfig。

正常产品仍采用依赖 boot/vendor_boot 的无内核 Recovery；r59 是另行打包的
独立镜像。触摸运行程序与固件依赖已由后续
[RECOVERY_TOUCH_PRODUCT.md](RECOVERY_TOUCH_PRODUCT.md) 完成正常模块构建和依赖检查。
正常完整镜像的内核/模块对应、AVB、
实际启动，以及非满电、物理充电切换与总入场时间仍需分别验证。
这项固件/UI 构建修正不代表整套 r59 standalone 镜像已经可由普通整包构建复现。
