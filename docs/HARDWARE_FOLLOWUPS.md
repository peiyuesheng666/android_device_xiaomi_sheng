# 平台功能接入

自动白平衡使用系统的 DisplayWhiteBalance 和前方色温传感器，配置见 [自动白平衡](DISPLAY_WHITE_BALANCE.md)。

注视感知通过 AttentionService 接入，应用按 [设备应用布局](PRODUCT_APPS.md) 安装；服务声明、权限和原生依赖应一起维护。相机及注视感知的现场操作单独安排。

关于设备的营销名称使用 `ro.product.marketname`，应用可见的硬件型号仍由 `ro.product.model` 及分区型号属性提供。两者用途不同。

自动息屏遵循系统超时和充电保持唤醒设置，不在每次启动时覆盖用户选择。基础功能的源码位置见 [硬件适配索引](HARDWARE_STATUS.md)。
