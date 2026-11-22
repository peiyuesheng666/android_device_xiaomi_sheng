# 杜比构建目标 SDK 一致性 — 2026-11-13

ShengDolby 的 manifest 已明确 min SDK 1、target SDK 37，Android.bp 补充
target_sdk_version: "37"，使模块声明明确表达同一目标。
音频实现、应用版本 3.0.2/code 51、原厂库和当前 r64 安装保持。

正常构建图中 aapt2 的 target SDK 默认值为 1，这是固定 Soong java/aar.go:406
主动沿用 minSdkVersion 的设计，即使声明 target_sdk_version 也保持此默认值。
实际应用目标由 manifest_fixer 和 manifest 确定。固定 Soong 源码
scripts/manifest_fixer.py:96 明确保留 manifest 中已有的 targetSdkVersion；
实际旧中间 manifest 及旧 APK 都是 target 37。aapt2 的此参数也提供默认值。
最初“下一次 APK 会写成 1”及“aapt2 默认值须改为 37”的推断均已纠正。
未发现杜比 SDK 降级故障，本项保留显式声明与正式验证记录，
不计为音频功能修复，不解释 QTI／Dolby 视频启动故障。

## 参考与实现范围

刷新 piano seventeen 至 8c0bb4b9d15ea349eaa09d6de0aa4fec43f7ff41，
检查 device.mk 与 dolby/DolbyManager/Android.bp；nuwa lineage-24.0 为
8e2b6ca4375919035587115189760eed64f14b8d，其 sm8550-common 为
62f4b9c1d20c88f02e0bc7f1b2c932bd5c750eb1。piano 应用使用平台签名、
system_ext 与 privileged，已有 sheng 对应配置保留。参考树的应用和依赖
不用于替换本树的 API 1 bootstrap 或音频实现。
构建处理依据是 ROM 固定 Soong a528a88bd553d2a449ad9338a3e944b89a164971；
未修改或升级公共源码。刷新回执与原始前置构建参数见
reports/device/20261113-dolby-sdk/reference-review.json 和 aapt-link-before.txt。

只同步这一份 Android.bp，保存原副本；独立模块使用正常
build_hardware.sh ShengDolby，SHENG_STAGE_FACE_ENGINE=0、四个构建任务。
现有 SSD swap 按构建工具启用，不新建 swap。构建前后校验 32 项
dolby/ShengDolby 输入并拒绝额外文件，重新抓取并审计公共源码。

## 验证

正常 ShengDolby 模块构建通过，用时 12:27；构建后公共源码审计通过，
扫描 1243 个项目无非清洁状态，前后 32 项源码镜像检查通过。
verify_sheng_dolby_apk.py 检查实际 APK min 1/target 37、DEX 035、v1 与
平台签名、16 KiB 对齐、Settings/音效面板入口、persistent/directBootAware、
反射加载的公开 AtmosApplication(Context) 构造器，以及实际 manifest_fixer
目标 37、aapt2 两个默认值 1。
上述 APK 检查全部通过。旧、新 APK 和 DEX 完全相同，归档内容无变化，
APK SHA-256 为 ee88f655315b690adede3d77fcd2995de29e63748c6975d394ec093f5dfa7e0b。
构建结束后原 Soong ELF 已恢复，未遗留构建包装器。
最终回执为 reports/device/20261113-dolby-sdk/final-build-status.json 和 verification.json，
完整构建证据封存于 artifacts/dolby-build-sdk-20261113。

核验器首次解析采用旧 aapt2 布尔格式，随后分别修正 SDK signer 的 Conscrypt
搜索路径、非 UTF-8/中文 cwd，以及错误的 aapt2 默认值断言；四次失败证据
分别保留，status-final.json 指向最终通过结果，不改写首次失败状态。
这些核验器调整未更改 APK 或构建源码，不需要重复模块构建。
完整产品和实际硬件音频本轮不新增验收；产物未变化，不刷写当前 APK。
