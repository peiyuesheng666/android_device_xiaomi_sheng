# 正常 Recovery 的触摸依赖（2026-11-13）

已验收的 r59 独立镜像使用原厂 `touch_report_debug` 将 NT36532 的触摸帧
转换成输入事件。正常产品此前只有驱动固件复制项，没有这个处理程序、两份
运行库、启动脚本和三个模型，亦未设置已验收的触摸坐标旋转。

本批将这些输入接入正常 Recovery 产品。Android 的已验收触摸栈不作更换，
本项也不代表 Focus Pen Pro 书写问题得到修复。

## 产品声明

`proprietary-files.txt` 为程序使用 `EXTRACT_ONLY;FILEGROUP`，两份现有库
使用 `FILEGROUP`。标准提取工具生成三个原始输入 filegroup，设备树定义
独立的 `sheng-recovery-touch-runtime`、`libsheng_recovery_touchsensor` 和
`libsheng_recovery_tensorflowlite_touch` 模块。三者仅供 Recovery 使用，
安装文件名、SONAME、原始 ELF 和依赖名称保持与 r59 相同，ELF 检查开启。
普通 ODM 库的模块声明保持原样。

程序的 init_rc 安装到 Recovery 的 `system/etc/init`，用已有 `touch.sh`
启动，保留设备等待、固件/模型存在检查和失败返回。`on init` 设置 r59 的
`ROTATION_RIGHT`，`on boot` 启动服务；不复制整个 standalone init 文件，
避免与正常固件和 USB 初始化重复注册。

三个模型安装在 `vendor/odm/firmware`，符合 Recovery 现有的
`/odm/firmware -> /vendor/odm/firmware` 链接；THP 配置仍用已有的
`vendor/firmware/n81a_nova_thp_config.ini`。7 项原厂输入的大小、SHA-256、
原始位置和安装位置记录于 `rootdir/recovery/touch-inputs.json`。
它们分别与原始 OS3.0.303.0.WNXCNXM 提取文件及已验收 r59 解包内容核对一致。

## 本地构建准备

新的完整源码环境通过正常 `extract-files.py` 提取和生成 vendor 声明。
已有本机镜像可使用 `tools/prepare_sheng_recovery_touch_product.py`，显式传入
`--rom`、含 odm/ 的只读 `--stock-root` 和新建 `--work`。
工具在写入前核对全部输入，不覆盖不同版本的已有 blob。随后运行标准
生成器，只合入三个 filegroup，保留其余现有 vendor 声明，并保存前后文件。
原 QTI 候选的依赖声明差异不在本批中清理。

`prepare_sheng_pen_settings_product.py --include-recovery` 同步完整 Recovery
源码、提取清单及触摸产品复制块；构建后的源码镜像检查覆盖同一范围。
6 项临时目录回归检查覆盖补齐输入、重复运行、CRLF、未知复制块和重复安装
目标拒绝。构建入口仍为正常的 `build_sheng_pen_settings_product.sh`，目标
包含上述三个模块及其脚本、RC、配置和模型安装路径。

## 验证状态

17:26 完成正常构建、构建后源码审计和产物核验。构建阶段耗时 11 分 42 秒，
71 项步骤全部通过，其中三个 prebuilt 的 ELF 检查均执行成功；34 项源码
镜像检查没有差异。实际 7 项输入哈希与 r59 相同，模型路径和唯一服务定义
通过；另对两份原有 NVT 驱动固件作了正常输出/原厂来源/r59 三方字节对照。

DT_NEEDED 依赖检查覆盖 10 个 ELF（含 linker64），660 项强导入符号均找到
可见且版本匹配的定义，无未解析项。固件/UI/策略检查再次通过，Recovery
专用类型未进入普通 Android 策略，permissive 域集合保持原样。
准备工具的重复运行不添加 blob，也不改变已有 vendor 文件内容；移除三个
新增 filegroup 后，vendor Android.bp 与本批前逐字节等价（忽略文件末尾空行）。

成功构建回执：WSL `hardware-diagnostics/sheng-pen-settings-20261112/`
下 `modules-20261113-091326-EMh6mQ/status.json`。
工作区证据在 `reports/device/20261113-full-product/`：
`touch-validation/verification.json`、`touch-vendor-scope.json`、
`touch-driver-firmware.json` 和 `touch-source-repeat.json`。
本批未打包或刷入镜像，Android r64 / Recovery r59 安装状态保持。

`verify_sheng_recovery_product.py --include-touch` 在固件/UI/策略核验基础上，
检查 7 个实际输出哈希、脚本和 RC、唯一服务定义、模型路径链接、程序执行位，
并递归检查实际 Recovery 输出中的 DT_NEEDED 和强导入符号（包含版本及
linker64 提供的符号）。这些是构建产物检查，不能代替一次完整镜像启动。

## 参考与未完成范围

沿用本轮已刷新的 piano `8c0bb4b9d15ea349eaa09d6de0aa4fec43f7ff41`、
nuwa `8e2b6ca4375919035587115189760eed64f14b8d` 和 sm8550-common
`62f4b9c1d20c88f02e0bc7f1b2c932bd5c750eb1`。piano 同样将自有触摸固件
放入 Recovery，nuwa 使用不同触控驱动；均不能直接替代 sheng 的帧处理程序。
本 ROM 的 extract-utils `78ba5d58c4b06712e18bb387a2a72eac8fbc8d70` 已重新
fetch、检查并用于实际生成，build/soong 固定为
`a528a88bd553d2a449ad9338a3e944b89a164971`。公共仓库未修改。

正常无内核 Recovery 与 boot/vendor_boot 的组合、模块加载和 AVB，以及新
完整镜像的启动/菜单触摸，仍需独立验收。现有 r59 用户验收继续保留，不能
将其转记成未安装的普通产品镜像已通过。固件与电池 UI 的前一批结果见
[RECOVERY_PRODUCT_INTEGRATION.md](RECOVERY_PRODUCT_INTEGRATION.md)。
