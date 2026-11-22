# 人脸引擎与系统服务

人脸识别引擎、模板存储和 Android 生物识别会话分别维护。共享图像处理代码位于 `interfaces/biometrics/softwareface`，原生服务位于 `interfaces/biometrics/systemface/native`。

系统录入、删除和锁屏认证通过原生 IFace、ISession 接入；独立引擎页面用于开发，不替代 Settings 与 Keyguard 的用户流程。应用统一遵循 product 布局，HAL 服务、运行库及 VINTF 声明按各自接口需求安装。

录入使用真实凭据授权，模板按用户隔离并加密保存。匹配结果不提升软件传感器的强度，不用于授权强生物识别加密操作。捕获与会话取消、息屏、用户切换和服务终止一起释放。

原生接口配置见 [原生人脸接口接入](FACE_NATIVE_INTEGRATION.md)。现场相机与锁屏操作单独安排。
