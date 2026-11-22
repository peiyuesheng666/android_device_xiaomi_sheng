# 外部手写笔接口资料

此目录保存配件身份、输入节点、压力传输和生命周期处理的参考资料。它不属于 sheng 的 Android 产品源码入口。

sheng 的设置应用、常驻服务、协议和原生后端位于 `interfaces/input`，使用本机触摸控制器 ABI、硬件描述符和独立实现。其他系统的配件管理 API、控制器参数和部署脚本不能作为本机接口定义。

`reference-receipt.json` 保存原始归档和选取文件的来源、哈希。原始说明的存放位置由该回执的 `local_documentation` 字段提供；当前 README 说明本地参考目录的用途。接口对应关系见 [手写笔接口参考](../../FOCUS_PEN_REFERENCE.md)。
