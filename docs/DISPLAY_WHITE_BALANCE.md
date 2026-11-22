# 自动白平衡

系统使用 Android DisplayWhiteBalance，根据前方环境色温调整显示矩阵。亮度来自标准环境光传感器，色温来自非唤醒的 `xiaomi.sensor.front_cct`。夜间模式、无色彩管理的饱和模式和部分无障碍颜色变换会影响白平衡的启用条件。

`overlay/FrameworkResOverlaySheng/res/values/display-white-balance-sensor.xml` 定义功能开关、原色和过渡参数。默认色温为 6500 K，调整范围为 5300–8100 K，低照度目标为 5600 K。冷色方向渐变为 3000 ms，暖色方向沿用系统的 40000 ms。

原色回退值采用 sRGB/D65 工作空间。名义白点使用框架 `cctToXyz(6500)` 对应的 XYZ，使默认色温的白平衡矩阵连续回到单位矩阵。原厂二维光照／色温表不能直接作为 Android 的一维映射表使用。

`aidl/sensors/ShengCctSample.h` 只拒绝准确匹配前方非唤醒 CCT 传感器的非有限或非正数样本。有效 Kelvin 数值保持原样，不按该传感器不可靠的 maxRange 元数据截断。没有有效样本时，框架可能保留上一色温；不能用虚构色温填补。

排查时依次读取 `dumpsys display`、`dumpsys color_display`、`dumpsys SurfaceFlinger` 和 DRM PCC 属性。系统矩阵、composer 缓存与内核提交参数属于不同观察点，实际环境效果需要单独判断。

`tools/ShengDrmColorProbe.c` 以只读方式打开 DRM 节点，只查询属性和 PCC 数据块，不访问像素或设置显示模式。`tools/capture_sheng_white_balance.py` 使用临时色温覆盖采集文本状态，并恢复覆盖值及屏幕状态；日志放在指定输出目录。覆盖命令需等传感器回调才会触发计算，必须以实际目标色温判断是否生效。
