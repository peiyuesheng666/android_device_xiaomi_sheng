# 指纹录入回归 — 2026-11-12

用户反馈再次无法录入，确认表现为“进不了录入页，或提示指纹硬件不可用”。
故障发生时为 ca10ede3 A，Android r61，5.15.220-gf9ca2b71f672，SELinux Enforcing；
boot_id 为 edd29c2a-3df0-4b3a-9e07-6c3683a0132d，与 r61 验收启动相同。

已通过只读 ADB 保存日志、dumpsys、路径标签和两份崩溃头。
没有提取指纹模板，没有删除数据、启动相机或刷写。

| 检查 | r61 故障捕获结果 |
| --- | --- |
| HAL 发现 | persist.vendor.sys.fp.vendor=fpc；服务运行。default 软链接正确，原厂 FPC 库 SHA-256 仍为 4388432669c5fe1cc52ebd5a343d190724a2417f60352a804b43b0900939bcbd。 |
| 数据目录 | /data/vendor/fpc 为 system:system 0770、vendor_fingerprint_data_file；不是早期漏软链接／错误数据标签故障。 |
| 两次录入尝试 | 21:27:03、21:27:13（Asia/Singapore）分别触发 HAL SIGABRT，Fingerprint::createSession 断言 Open session already exists；framework 记录 HAL deaths=2。 |
| FPC 控制节点 | wakeup_enable 实际为 sysfs_wakeup；HAL 对它的 write 被 SELinux 拒绝。其他检查到的设备控制节点仍为 sysfs_fingerprint_sheng。 |
| r61 标签回归 | genfscon 的 /soc:fingerprint_fpc/wakeup 是字符前缀匹配，也覆盖同级 wakeup_enable，原先所谓“控制节点保持标签”未覆盖该路径。应添加更具体的控制节点映射，保留统计目录和现有权限。 |
| 会话因果链 | wakeup_enable 写入失败后，FPC 采集返回 -6／FPC_ERROR_IO，HAL 回调 HW_UNAVAILABLE；framework 清空当前会话引用，但 HAL 原会话仍打开，再次 createSession 触发断言。只恢复标签并重启 HAL 后实际录入及认证恢复。 |

## 临时修正和永久 r62 修正已通过

对唯一控制节点临时 chcon 为 sysfs_fingerprint_sheng，然后仅重启
vendor.fingerprint-default。保持 Enforcing，原统计目录和实例仍为 sysfs_wakeup，
没有修改节点值、添加权限或清除数据。用户复测回答“已能完成录入”。
系统回读记录 1 个指纹、5 次成功认证；HAL PID 保持 6077，死亡计数仍为原来的 2。
证据为 hotfix-user-acceptance.json、user-enrollment-after-hotfix.txt 和 after-hotfix-logcat.txt。

设备树已补精确 genfscon，验证器增加真实控制文件标签检查。r62 于
2026-11-12 21:53（Asia/Singapore）刷入 vendor A 与配套 vbmeta A；唯一文件变化
为 vendor 的 etc/selinux/vendor_sepolicy.cil，唯一策略新增为 wakeup_enable 的
精确控制标签，不增加 allow 规则。正常 policy 模块构建、源码镜像、公共源码审计、
实际分区组合 neverallow、编译后 libsepol 前缀查找和完整 AVB 链均通过。

重启后的 r62-runtime/runtime.json 已通过全部 14 项分区和依赖哈希回读。
boot_id 为 f2a3feea-317c-4c08-9d41-d70f303db01d；Enforcing 下控制节点为
sysfs_fingerprint_sheng，五个 wakeup 实例的 50 项统计仍为 sysfs_wakeup，
真实 suspend 服务可读取全部实例。系统保留 1 个指纹，记录 2 次成功认证，
HAL deaths since last reboot 为 0。用户在随后聊天明确反馈“指纹功能已经正常”。
当前指纹录入与认证按用户验收标记正常；长期待机后的认证稳定性仍须单独验收。

| r62 更新分区 | SHA-256 |
| --- | --- |
| vendor | ad33c537260d8bf0e4a5c1dda26f0dfb430c38e76d68165ef1a72b7c0aa28ecd |
| vbmeta | 66a49c059044f4f12fb3df6524f71126ede82b72d3e337dc75f2bbfb22cb5933 |

包装清单中的 hardware_boot_tested=false 是发布时尚未安装的状态，清单保持封存；
后续安装结论以独立 r62-runtime/runtime.json 和用户反馈为准。完整产品构建
仍未验收，原厂 QTI、原版 SystemUI、Recovery r59 及其余分区保持原基线。

原始证据在 workspace reports/device/20261112-fingerprint-regression/：
baseline.txt、paths.txt、dumpsys-fingerprint.txt、logcat.txt、crash-headers.txt。
永久更新证据同在该目录：normal-policy-build.log、r62-normal-build-status.json、
r62-source-mirror.json、r62-upstream-audit.json、policy-scope-guard-tests.json、
flash-r62-20261112-215232.txt、r62-runtime/runtime.json 和 fingerprint-state.txt。
包装与实际策略验证回执为 artifacts/system-hardware-followup-sheng-r62/build-result.json。
历史 r13 与本次临时修正验收保留；当前基线为已永久修正并验收的 r62。
