# ROM 产品入口

同一份设备树提供 LineageOS 和 PixelOS 产品。硬件配置、手写笔、输入法、音频、显示、权限与私有驱动共用 `device.mk`；设备身份和 product 应用约束集中在 `product-common.mk`。

| ROM | 产品入口 | Lunch | 完整构建目标 |
| --- | --- | --- | --- |
| LineageOS | `lineage_sheng.mk` | `lineage_sheng-cp2a-userdebug` | `m bacon` |
| PixelOS | `custom_sheng.mk` | `custom_sheng-cp2a-userdebug` | `m pixelos` |

PixelOS 的平板配置从 `vendor/custom` 进入，并继承其源码清单中的 `vendor/lineage` 公共配置。两种产品共用分区预留策略和硬件接口；Lineage 平台资源覆盖仅在源码包含对应资源包时安装。

将设备树放到 `device/xiaomi/sheng`，私有驱动放到 `vendor/xiaomi/sheng`。两种产品使用相同的内核、板级设备树和模块输入；切换 ROM 不应混用其他内核的模块。

在对应 ROM 源码根目录加载 `build/envsetup.sh` 后选择产品。公共 ROM 源码保持各自清单的内容，板级差异在本设备树维护。应用包名、签名要求、服务身份及 product 安装位置随硬件功能维护，不随 ROM 品牌重命名。

首次构建使用空输出目录和对应 ROM 的完整构建目标。切换 ROM 时使用独立源码与输出目录。后续局部修复复用同一 ROM 的产物进行增量编译，集中修改完成后再构建完整产品。

`tools/build_hardware.sh --full` 根据源码中的 ROM 配置选择完整构建目标；也可通过 `SHENG_LUNCH` 明确指定产品。设置 `SHENG_ROM_ROOT` 可从外部工作区调用。省略 `--full` 时接受模块名用于局部编译。入口共用输出锁、product 应用检查、保留的人脸引擎校验与 C 盘交换区检查。
