# 呼吸灯

2026-11-15 用户撤销了呼吸灯开关需求，要求移除选项并默认关闭。PixelOS 的普通、桌面及中文布局均已移除「设置 → 系统 → 互动 → 呼吸灯」，产品不再安装 ShengIndicatorSettings。

设备树内的 QTI Light AIDL 服务继续使用 RGB LED 的 `brightness`、`trigger` 和 `breath` 硬件接口。总开关只控制这颗指示灯的输出，系统充电和通知逻辑继续提交正常状态。没有设置过开关时，应用和服务都采用关闭值。

持久化属性为 `persist.sys.sheng.indicator`，不存在时仍默认 false。本次升级将旧值清为 false，并读取 red、green、blue 的 brightness 均为 0；重启后验证 false 保留。灯服务只读取该属性，和系统灯光请求共用互斥锁。相机状态不改变这项关闭策略。

硬件服务和设置资源覆盖均由本设备树构建；公共 Settings、framework 和内核源码无需修改。旧 QTI 服务的二进制、init 配置和 VINTF 条目不再由提取清单安装，产品中仅安装一套 Light AIDL 服务。旧设置应用源码仅保留供历史参考，不在产品安装列表中。
