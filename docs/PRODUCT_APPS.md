# 设备应用布局

设备新增应用统一安装到 `product`。普通应用放在 `product/app`，需要特权权限的应用放在 `product/priv-app`。

| 应用 | 目录 |
| --- | --- |
| 手写笔设置 | `product/app/ShengPenSettings` |
| 手写笔服务 | `product/priv-app/ShengStylus` |
| 杜比设置 | `product/priv-app/ShengDolby` |
| 键盘连接管理 | `product/priv-app/ShengKeyboardPresence` |
| 触控设置 | `product/priv-app/ShengTouch` |
| 显示默认设置 | `product/priv-app/ShengDisplayDefaults` |
| 人脸应用 | `product/priv-app/ShengFaceUnlock` |
| 网络定位 | `product/priv-app/ShengMetokNLP` |
| 注视感知服务 | `product/app/MiAONService` |

应用及配套文件的清单位于 `configs/product-apps.json`。新增应用需加入清单，并在模块中设置 `product_specific: true`。

特权权限白名单放在 `product/etc/permissions`，默认授权放在 `product/etc/default-permissions`。应用调用平台接口所需的产品配置位于 `product-common.mk`。

LineageOS 与 PixelOS 保留各自的默认输入法。设备树不预装搜狗，不覆盖 ROM 自带输入法，也不强制修改默认输入法选择。

这些设备应用与系统框架一起编译。`PRODUCT_ENFORCE_PRODUCT_PARTITION_INTERFACE` 使用 Make 的 `override` 赋值关闭稳定接口限制，防止构建系统按出厂 API 自动覆盖配置。应用签名、特权授权和 SELinux 规则各自生效。

运行 `tools/audit_sheng_product_apps.py --output <输出文件>` 可以检查应用及权限文件的安装位置。正常设备构建入口也会执行此检查。

`tools/sync_sheng_product_apps.py --output <备份目录>` 同步独立构建树中的应用布局，并保留被替换文件。`tools/verify_sheng_product_config.py --output <输出目录>` 读取实际产品配置，检查安装分区、应用清单和平台接口设置，不启动模块或系统镜像构建。
