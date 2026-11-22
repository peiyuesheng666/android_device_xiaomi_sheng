# APE 音频接入

`libshengapeextractor` 将 APE 文件接入 Android 的 MediaExtractor，向 Codec2 提供 `audio/x-ape` 音轨、初始化信息、帧数据和时间戳。原生解析库安装在 `system_ext/lib64/extractors`，由系统媒体解析服务加载。

解析器处理带描述头和完整寻址表的现代 APE 容器，支持单声道或双声道、16 位 PCM、8–192 kHz 采样率，以及 fast、normal、high 压缩模式。输入需要提供长度和随机读取能力，文件大小不得超过 32 位寻址范围。旧式文件头、extra high 与 insane 压缩、其他 PCM 位深不在接入范围内。

文件头、音频范围、寻址表和帧大小都有上限及越界检查。帧数据按照解码器要求对齐，尾部标签不送入解码器。拖动进度通过寻址表定位帧，支持前一帧、后一帧和最近帧三种同步点选择。

设备配置 `configs/audio/media_codecs_c2_audio.xml` 引入公共音频配置，再设置 APE 解码器选择。原公共配置以 `media_codecs_c2_audio_base.xml` 安装，其他格式的配置继续由它提供。APE 默认使用 `c2.qti.ape.hw.decoder`；软件后端会丢弃最后短帧的部分 PCM，因此不向应用公布该软件组件。

`device.mk` 声明解析库和两份音频配置。`interfaces/media/ape` 保存独立的容器解析与系统接口实现，`tools/build_sheng_ape_extractor.py` 提供使用现有平台依赖的针对性编译入口。
