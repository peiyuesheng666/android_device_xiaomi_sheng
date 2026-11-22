# 构建进程与输出归属

`tools/build_hardware.sh` 与手写笔、Recovery 构建入口共用 `out/.sheng-device-modules.lock`。入口先获取非阻塞锁，再核对编译器备份和分析进程，随后同步源码、准备依赖并构建。同一输出目录只能由一个构建入口持有。

退出时只恢复本次创建且未被外部修改的编译器包装器。遇到其他进程的备份、未知输出或外部改动时保留原文件并返回错误，避免覆盖另一个构建的产物。

Ninja 图检查使用产品的 combined graph；其中声明的任务池与被包含的 Soong 图一起解析。不得为绕过解析错误手工修改生成的 Ninja 规则。

`SHENG_BUILD_JOBS` 控制编译并行度，允许范围为 1–24。分析阶段的 CPU、内存限制与高内存任务池单独管理。`SHENG_STAGE_FACE_ENGINE=0` 仅跳过人脸引擎依赖准备，不改变设备上的服务或相机状态。

交换区与资源保护见 [构建交换区配置](BUILD_SWAP_STORAGE.md)。公共源码固定方式见 [源码策略](SOURCE_POLICY.md)，源码镜像检查见 [源码镜像一致性](SOURCE_MIRROR_RECONCILIATION.md)。
