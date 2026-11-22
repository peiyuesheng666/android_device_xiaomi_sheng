# Codec2 字段向量依赖检查

`tools/audit_sheng_qti_fieldlist_consumers.py` 扫描 vendor ELF 的字段向量定义、C2FieldList 与 C2ParamUtils 引用，以及对应动态重定位，用于审查 Codec2 插件的加载组。

相关提供者包括平台 VNDK、QTI filterbase、音频 basecodec、颜色转换、过滤器、VPP 和视频 codec。已定义的全局对象同样可能经过按名称解析的重定位，不能只查未定义符号来决定是否移除导出。

重定位读取必须支持 Android packed 格式，并核对已知字段引用。扫描输出保留各输入的哈希、定义与引用，便于检查真实依赖闭包和跨库对象归属。

加载方案见 [QTI 字段对象与加载归属](QTI_FIELD_OWNERSHIP.md)。
