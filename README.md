# Device tree for Xiaomi Pad 6S Pro 12.4 (`sheng`)

小米平板 6S Pro 12.4 设备树，支持 PixelOS / LineageOS 产品入口。

![Xiaomi Pad 6S Pro 12.4](https://i02.appmifile.com/mi-com-product/fly-birds/xiaomi-pad-6s-pro-124/pc/e22707982190cc2587fde3afa3d54567.jpg)

## 硬件规格

| 项目 | 规格 |
| --- | --- |
| 设备代号 | `sheng` |
| 型号（国行） | `24018RPACC` |
| SoC | Qualcomm Snapdragon 8 Gen 2 |
| 内存 / 存储类型 | LPDDR5X / UFS 4.0 |
| 显示屏 | 12.4 英寸 LCD，3048 × 2032，3:2，最高 144 Hz |
| 屏幕亮度 | 700 nit（典型），900 nit（HBM） |
| 后置摄像头 | 50 MP 主摄 + 2 MP 景深 |
| 前置摄像头 | 32 MP |
| 电池 | 10000 mAh（典型） |
| 充电 | 120 W 小米澎湃秒充 |
| USB | USB Type-C，USB 3.2 Gen 1，最高 5 Gbps |
| 无线连接 | Wi-Fi 7，Bluetooth 5.3 |
| 指纹 | 支持指纹识别 |
| 传感器 | 加速度计、陀螺仪、光线、距离、电子罗盘、霍尔、频闪、色温 |
| 尺寸 | 278.70 × 191.58 × 6.26 mm |
| 重量 | 590 g |
| 出厂系统 | Xiaomi HyperOS，基于 Android 14 |

规格参考[小米官方参数](https://www.mi.com/global/product/xiaomi-pad-6s-pro-124/specs/)。
表中为硬件规格，不代表第三方 ROM 已实现全部原厂功能。

## 源码布局

设备树放在 `device/xiaomi/sheng`，厂商文件放在 `vendor/xiaomi/sheng`。
当前内核为 Android 17 Linux 6.18.39，源码项目放在 `kernel/xiaomi/sheng-build`；
`kernel/xiaomi/sheng` 链接到该项目的 `sources/k618/ws/common`。

完整构建步骤见 [BUILD.md](BUILD.md)。

## 方向与显示

传感器在 SSC 层使用平板的自然横屏坐标，加速度、陀螺仪、磁场、融合方向与直接通道
使用一致的基准。已有校准系数随坐标转换，持久注册文件的写入顺序适配 SSC 解析器，
迁移支持重复执行和中断恢复。

透明图层混用色域时，显示合成采用稳定的 GPU 客户端策略，避免媒体查看器出现缺块
和交替闪烁；受保护内容继续使用原有安全显示路径。

ShengDisplayDefaults 在开机、用户初始化与应用安装后应用系统全屏默认策略，保留
用户指定的宽高比。特权权限与应用共同安装到 product。
