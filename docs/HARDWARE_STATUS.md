# sheng 硬件适配索引

| 模块 | 配置与实现 |
| --- | --- |
| 显示 | `interfaces/display` 提供 composer、gralloc、色彩管理和显示设置。环境白平衡沿传感器、系统色彩控制和显示矩阵通路工作。 |
| 触摸 | `interfaces/input/touch` 管理触摸选项，输入方向和唤醒权限由设备配置提供。 |
| 手写笔 | `interfaces/input/pen` 提供设置页；`interfaces/input/stylus` 管理笔的连接、电量、充电提示和输入协作。 |
| 手写输入 | 手写识别由当前输入法提供；两个 ROM 保留各自的默认输入法和用户选择。 |
| 键盘 | `interfaces/input/keyboard` 管理连接状态与翻折后的输入启停。 |
| 音频 | `interfaces/audio` 管理设备音频接口；`dolby` 提供音效设置及适配。 |
| 媒体 | `interfaces/compat/codec2` 提供 QTI 音视频及 Dolby 服务入口；动态解码库由提取清单和模块依赖管理。 |
| 定位 | `interfaces/location` 接入系统网络定位和地理编码。 |
| 指纹与人脸 | `interfaces/biometrics` 管理设备生物识别适配；人脸现场验证单独安排。 |
| 电源与传感器 | `rootdir`、`properties`、`configs` 与 `sepolicy` 管理节点、服务和访问权限。 |
| Recovery | `rootdir/recovery` 管理启动、触摸、存储和电池界面。 |
| 内核集成 | `interfaces/kernel` 管理设备所需接口和预编译产物集成。 |

新增应用的分区和权限布局见 `PRODUCT_APPS.md`。手写笔设置与输入协作见 `FOCUS_PEN_INTEGRATION.md`。Codec2 的加载、安装和检查方式见 `interfaces/compat/codec2/README-qti.md`。

各功能的运行状态及剩余事项由工作区 reports 中的结构化记录维护，此文档只说明设备树的配置位置。
