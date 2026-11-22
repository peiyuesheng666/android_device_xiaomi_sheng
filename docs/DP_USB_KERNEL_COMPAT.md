# sheng 6.18 DP 与 USB PHY 兼容配置

原厂 sheng DT 把 4nm-v1.1 DP PLL 资源和时钟提供者放在 DP display 节点中。当前 Qualcomm 显示驱动使用独立的 `qcom,dp-pll` 节点。设备构建入口 `tools/build_sheng_source_modules.py` 在准备模块源码后运行 `tools/prepare_sheng_dp_usb.py`，补上旧布局的兼容路径。兼容路径限定根节点 model 为 `Qualcomm Technologies, Inc. 8550 sheng`、PLL revision 为 `4nm-v1.1` 且节点提供时钟。独立 PLL 节点沿用原有初始化路径。

PLL 的时钟提供者和成功注册的时钟按所有权释放，初始化部分失败时也清理已经取得的资源。USB PHY 的 GCC XO 消费者引用通过 `clk_hw_get_clk()` 取得，并由 PHY 的 devres 回调调用 `clk_put()`，避免把 GCC 注册的时钟交给要求同设备所有权的 `devm_clk_hw_get_clk()`。

原厂驱动为较新控制器内置 HBR2/HBR3 和 HBR/RBR 训练参数，当前驱动改为读取设备树的四组参数。旧 sheng DT 没有这些属性。`sheng_dp_legacy_lt.h` 保留原厂四组参数，仅在该机型、PHY 6.x、控制器版本至少 1.2.3 且未提供有效 DT 参数时使用；显式 DT 参数仍优先。`dp-refresh-compat.patch` 展示这部分改动。链路状态读取使用返回字节数的 DPCD 接口，与现有长度检查一致，避免把新内核接口的成功返回值 0 误记为失败。

准备源码时可以运行：

```sh
python3 device/xiaomi/sheng/tools/prepare_sheng_dp_usb.py --source-root /path/to/prepared/k618
python3 device/xiaomi/sheng/tools/prepare_sheng_dp_usb.py --source-root /path/to/prepared/k618 --check
python3 device/xiaomi/sheng/tools/test_sheng_dp_usb.py --source-root /path/to/prepared/k618
```

变换脚本检查全部输入再写入，重复运行不会重复插入。`interfaces/kernel/6.18/dp-usb-compat.patch` 提供对应变更供审阅。主机测试抽取实际 C 函数并注入分配、资源和时钟注册失败，不能替代实际 DP 链路训练或 USB SuperSpeed 传输测试。

本地维护工具 `build_sheng_dp_usb_modules.py`、`qualify_sheng_dp_usb_modules.py` 使用指定的诊断构建目录，编译两个模块并核对导入 CRC、导出、vermagic、模块签名和 BTF。`package_sheng_dp_usb.py` 基于已备份的活动 vendor_boot 只替换两个模块，保留 DTB、bootconfig 和其他 ramdisk 内容。工具中的诊断目录及基线是本地维护配置，迁移机器或基线后须重新核对。

测试安装需要同时更新 vendor_boot 内的早期模块和 vendor 的模块副本，单独替换 vendor 副本不会改变本次启动早期已加载的驱动。安装前保留活动分区和模块备份，检查设备序列号、槽位和基线哈希。安装工具将现有无线 ADB 端口临时保留到测试重启，启动验证后须恢复原属性值。

运行时先检查 DP PLL 初始化信息、DRM DP connector、USB PHY 警告，再用转接器和显示器验证插拔、AUX 与链路训练。USB 根集线器的 10000M 能力不能证明外设已使用 USB 3；实际速率需在连接 USB 3 外设后检查该设备的 sysfs speed 并测试传输。

构建、安装和运行记录保存在工作区 `reports/dp-usb-kernel-*.json` 与 `reports/dp-live-20261118/`，产物和回退镜像保存在 `artifacts/dp-usb-kernel-20261118/`。

2026-11-18 复测发现 HBR2 双通道时钟恢复成功、均衡失败；驱动先减少通道，继而降速，最终以 HBR 单通道输出 1080p30。准备脚本现在为 sheng 在降低速率时恢复最初协商的通道数，先尝试低速率完整通道；到最低速率后不反复恢复，保留减少通道的回退能力。每次重试在开启链路时钟前刷新 PHY 通道元数据，防止 PLL 使用旧通道配置。不强制超出训练带宽的显示模式。`tools/test_dp_lane_retry.py` 抽取实际驱动函数验证降档、最低速率终止和机型范围。候选通过主机测试、ABI/BTF 和打包校验，实际训练结果尚待刷入复测。
