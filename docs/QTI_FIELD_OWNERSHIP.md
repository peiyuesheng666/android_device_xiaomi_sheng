# QTI 字段对象与加载归属

QTI 插件和平台 Codec2 库包含同名 `_FIELD_LIST` 全局向量。每个提供者都带有构造和析构逻辑；若 ELF 符号抢占把多个提供者绑定到同一个对象，便会破坏分配与释放的归属。

轻量 bootstrap 不直接依赖 Codec2。`qti_load_groups.h` 为字段向量提供者建立独立的 `RTLD_LOCAL` 加载组，再加载使用平台 ComponentStore 的 payload。提供者、工厂与插件句柄在组件生存期间保持有效。

检查加载关系时同时查看动态符号、完整依赖闭包及 Android packed relocation。仅查看直接 DT_NEEDED，或把无法解码的重定位当作无引用，无法判断字段对象归属。

`RTLD_LOCAL` 本身不能消除同一依赖组内的抢占；`RTLD_NODELETE` 也不会取消正常进程退出时的析构。不能通过跳过退出、拦截析构或修改原厂对象字节来隐藏所有权缺陷。

工厂生命周期检查与 HIDL 输出池检查使用不同的诊断入口。前者检查创建、释放及自然退出；后者释放组件和池后保留临时 Binder 服务，由运行器显式停止。打包工具拒绝诊断产物。

音视频配置及构建入口见 [Codec2 接入](../interfaces/compat/codec2/README-qti.md)。
