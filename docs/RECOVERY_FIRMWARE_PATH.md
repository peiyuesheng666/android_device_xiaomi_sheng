# Recovery 固件路径与电池初始化

2026-11-12，目标为 ca10ede3 的 A 槽类原生系统。r54 已构建、安装和回读，
后续 r55 保留这项修复。Recovery 内核仍为原有 5.15.220；这不是 6.18 整包验收。

## 故障与修复

r13 的 init 尝试写 `/sys/module/firmware_class/parameters/path` 时被 SELinux
拒绝，节点沿用 `/lib/firmware`，ADSP 找不到 `adsp.mdt`，电池 supply 没有注册。
原有 Recovery UI 在读取失败后使用 100% 的默认值，因此默认值不能证明真实电量。
此前临时设置 `/firmware/image` 并启动 ADSP 后，电池节点和有效 health 数据恢复。

设备树为这个确切节点添加 Recovery 专用类型、genfs 标签及 init 的 open/write
权限；Recovery 服务只读取该路径。类型、标签和权限均使用 `recovery_only`，
已分别展开 Recovery/正常系统宏验证其适用范围。启动脚本检查路径和完整固件，
只在 ADSP offline 时请求启动，缺少固件或处理器时明确失败。

## 构建和实机证据

使用保留的 recovery_sepolicy.conf 复现 r13 策略，SHA-256 与已安装版本一致，
再编译设备源码中的最小增量。checkpolicy、secilc neverallow 检查开启；
已有 permissive 域名单相同，未添加新的 permissive 域。
全局为 Enforcing，但上游 Recovery 域本身已有 permissive 声明，不能将全局状态
描述为所有域均强制。此次路径写入由 Enforcing 的 init 域完成。

r54 镜像只改变策略和硬件启动脚本，保留内核、DTB、DTBO、模块与其他文件模式。
AVB 验证、重新解包校验和 A 槽完整分区哈希回读通过。r54 的 ADSP 约 4.7 秒
自动运行，约 7 秒取得有效电量、电压、温度、电流和循环计数；路径相关拒绝消失。
Recovery B、boot A、dtbo A 哈希保持。

证据位于工作区 `reports/device/20261112-recovery-pen/` 的
`policy-build-receipt.json`、`recovery-package-receipt.json`、`r54-runtime.json`
和对应启动日志。r54 镜像 SHA-256：
`c6de10c5af25cb5fdb0a1258d520a669222c47394399f3da75c017421a0490ef`。

这次是可复现原策略基线上的 scoped policy/native 构建，完整 Soong 产品构建
未通过。设备当前实际满电，非满电百分比准确性仍待对照 Android 验证。
用户确认 r54 进入时仍黑屏约 5～10 秒，随后菜单正常；显示等待另由 r55 处理，
详见 [RECOVERY_UI_STARTUP.md](RECOVERY_UI_STARTUP.md)。

## 参考

已刷新 piano seventeen 至 `8c0bb4b9d15ea349eaa09d6de0aa4fec43f7ff41`，
nuwa lineage-24.0 至 `8e2b6ca4375919035587115189760eed64f14b8d`，
sm8550-common 至 `62f4b9c1d20c88f02e0bc7f1b2c932bd5c750eb1`。
它们的 Recovery 分区/模块设计可作参考，没有可直接套用的 sheng 固件路径修复。
公共 system/sepolicy 使用本 ROM 固定版本，预构建 upstream audit 已通过。

构建工具为 `tools/build_sheng_recovery_firmware_r54.py` 与
`tools/package_sheng_recovery_firmware_r54.py`；本地 WSL 路径和保留输出是其显式依赖。
正常完整产品使用设备树里的策略与 init 配置，不修改公共仓库。
