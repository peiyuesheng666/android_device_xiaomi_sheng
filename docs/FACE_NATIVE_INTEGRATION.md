# 原生人脸接口接入

`interfaces/biometrics/systemface/native` 提供 Android 的 IFace、ISession 适配，由原生 Settings 管理录入和删除、Keyguard 管理认证。识别引擎和界面入口分开维护，不添加替代原生流程的额外设置页。

`NativeFaceProvider` 管理传感器及会话；`NativeFaceSession` 处理挑战、录入、认证、取消、枚举、删除、超时和锁定。`FaceCapture` 管理 Camera2、预览 Surface 与图像处理；`FaceRepository` 管理按用户隔离的加密 CE 模板。

软件人脸传感器使用 CONVENIENCE 强度，不能声明为 STRONG 或授权生物识别绑定的加密操作。录入前通过 `CredentialTokenVerifier` 验证真实凭据令牌及挑战，认证成功必须来自实际模板匹配。

框架回调、令牌序列化、Session 接口及预览生命周期需要与 ROM 固定的接口一致。服务声明、VINTF 片段、引导库、原生依赖和权限应作为一个组合维护；实际应用仍遵循 product 分区布局。

服务崩溃、取消或用户切换时释放捕获资源并结束当前操作，不把旧回调或上一位用户的模板带入新会话。现场录入与锁屏流程单独安排，设备排查不自动开启相机或 AON。

2026-11-15 的预览排查：最初针对 Settings FaceSquareFrameLayout 的比例覆盖虽编译通过，但用户实际打开的是 PixelOS 自带 `co.aospa.sense/.activities.EnrollActivity`，相机日志也记录客户端为 `co.aospa.sense`。针对 Settings 的实验覆盖未解决用户报告的问题，已撤回，原始布局及构建收据保留在 reports 中。这不应被记为人脸预览修复通过。

实际 Sense 页面使用固定 240×320 dp 的 CircleSurfaceView；其 FaceEnrollController 日志确认预览为 640×480，sheng 自然方向为横屏、前摄朝向为 0。横屏时相机图像未旋转，显示窗口却仍使用竖向比例，造成横向压窄。PixelOS 产品新增 `ParanoidSenseResOverlaySheng`，默认布局保留原 240×320 dp，横屏布局改为 320×240 dp。原 CircleSurfaceView、圆形进度、target 资源 ID、识别流程和相机选择均不变，不修改公共应用源码或已录模板。平台签名与目标 APK 一致，idmap 保留策略校验。源码同步、局部部署和实机结果见 sense-preview-* 及 sense-and-pen-balance-deployment；横竖屏视觉结果仍需用户验收，尤其需留意多窗口中窗口方向与物理显示方向不同的情况。

部署后，用户以此前出现“又瘦又长”的横屏姿势复测，明确确认“比例恢复正常”。该横屏场景已通过视觉验收；竖屏及多窗口仍保留回归项。
