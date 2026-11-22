# 键盘连接与翻折输入

`ShengKeyboardPresence` 是安装在 `product/priv-app` 的平台签名常驻应用。它结合键盘缓存连接状态与系统 `IInputManager.isInTabletMode()` 接口管理外设输入。

内核会长期注册 Xiaomi HID 端点，因此输入节点存在不代表键盘已连接。连接状态读取 `_version176x` 缓存；保护盖翻折状态来自 `SW_TABLET_MODE`，与控制合盖息屏的 `SW_LID` 分开处理。

应用只控制匹配 Xiaomi 厂商、产品及名称的键盘端点。拆下或翻折时关闭相关输入，恢复输入前进行短暂防抖。只恢复本应用关闭的端点，并在设备保护存储中记录控制归属；未知状态释放本应用的控制。

连接状态通过缓存节点只读获取，输入启停通过系统 InputManager 管理。原厂 `keyboardnanoapp` HAL、`MiDevAuthService` 和认证守护服务保留独立的 SELinux 域及必要的 Binder、TEE 权限。应用权限及安装分区见 [设备应用布局](PRODUCT_APPS.md)。

控制器在连接或亮屏时，通过原厂 HAL 发送正常激活请求，并使用原厂 APK 完成挑战和 token 校验。触控板功能命令等待真实认证与唤醒状态，再根据用户开关及翻折状态恢复。设备不安装持续保持唤醒服务，也不周期写入驱动休眠控制节点；正常空闲和熄屏休眠保留。端点存在、服务启动或协议应答均不能单独证明实际按键和触控板输入正常，稳定性需要在静置、熄屏和重新连接场景实测。

## 键盘背光反复亮灭（历史问题，待实机回归）

用户确认对象是实体键盘背光，不是平板屏幕，也不是首键输入延迟。用户确认现在不再出现；只列为回归检查，不作为当前故障。与旧驱动的 12 秒周期电源任务是否有关尚无证据。实测分别观察熄屏后按实体键、静置是否有周期性亮灭，以及恢复后的亮度是否稳定；和亮度控制功能分开记结果。

## Keyboard backlight brightness (pending)

此项与开机报错分开交付：目标是设置里可调实体键盘背光、支持关闭，并在摘装、翻折和息屏唤醒后按原厂行为恢复。设备端亮度和 Fn 同步不能以应用提交成功代替实物验收。

Track backlight brightness as a separate feature from keyboard detection,
panel wake, and the opt-in desktop switch. Match the stock ROM's controls and
visible brightness steps, including off. Capture the stock behavior before
choosing the UI and implementation. On sheng, verify each brightness step,
keyboard detach/reattach, and suspend/resume; do not mark this complete based
on the keyboard working or a backlight node being present.

### 2026-11-21 实机基线（只读）

Native05 的 `_b` 槽正常进入 Android，SELinux 为 Enforcing。`dumpsys input`
显示 `KbdBacklightController: 0 keyboard backlights`，`/sys/class/leds`
只列出键盘的 Num/Caps 等状态灯，没有可用的键盘背光节点。这说明不能只加一个
设置按钮就交付；不代表键盘硬件没有背光，也不能据此认定原厂走哪套接口。

先用现存的原厂资料确认控制路径、亮度档位和熄屏行为，再决定如何接入 sheng。
不猜测或试写 HID 命令，不把状态灯当背光，也不复用桌面模式开关。
验收需覆盖各档及关闭、摘装、息屏唤醒，并与原厂实际效果对照。

### 原厂协议取证（C 盘 WSL，未下发命令）

C 盘 Ubuntu 的 `/root/sheng-pixelos/midev-reference` 中，原厂参考代码的
`MiuiKeyboardManager` 将亮度设置交给 `BackLightFeature`；IIC 路径的
`IICKeyboard.setBackLight` 经 `IICProtocolDispatcher.setKeyboardBacklight`
调用同一短报文构造器，使用 feature `0x23` 和一个亮度字节，并对成功回包
单独记日志。该报文结构与本设备应用现有短报文构造器一致；它不是状态灯控制，
也不是当前应用中的 `0x25` 电源开关。

仍需要 `BackLightFeature` 原始实现或原厂实机行为来确认：键盘型号能力门控、
关闭与各档的字节值、Fn 键与设置同步、休眠与唤醒恢复。相邻的
`MiuiKeyboardUtil` 亮度映射在未核对调用方前不能当作键盘口的亮度档位。
本次只读取参考资料，未把推测值写进设备程序，也没有向平板发背光报文。

### 原厂亮度策略补证

从 C 盘现存原厂 `miui-services.jar`（SHA-256
`f12f4f1561e726d65b70a4e15a7805c70ef66d23ce19866bb8bc96a45af28d7f`）
单类检查 `BackLightFeature` 和 `FeatureSupport`：0 是关闭，自动亮度使用
0–100 的百分比，可按整数做渐变；光照映射并不是手动 UI 档位表。
IIC 路径从键盘版本回复取型号，触控板型 16、32、33 置能力位 `0x200`，
而 `FeatureSupport` 正是用该位判断背光支持。原厂禁用键盘时发 0，
唤醒、重连或启用时恢复所存亮度，不在睡眠期间强制唤醒键盘。
编码器已限制在已证实的 0–100，离线报文测试 147 项通过；尚未接入运行时。
手动设置入口、Fn 步进及实物验收仍待完成。

原厂按键/设置入口补查：`MiuiInputManagerService` 的读取和写入接口都转到
同一键盘管理器，实际写入仍经过原厂背光能力门控。当前保留的原厂 Settings 中，
实体键盘页面的 `keyboard_back_light` 是布尔开关，和驱动遵循的百分比不是同一设置。
在原厂 `MIUISystemUIPlugin.apk` 找到 Binder 接口声明与分派代码，尚未找到以固定档距
调用它的 Fn 处理源码；不能从接口声明、系统屏幕亮度热键或自动亮度映射推断 Fn 步进。
当前设备树滑条用自己的 Secure 设置值，不改原厂设置键，且尚待实机验证。

### 实机验收清单（候选未安装）

1. 记录启动 ID、槽位、键盘包路径以及候选 SHA-256。安装/刷写另行确认；不清数据、不换槽。
2. 从「实体键盘 → 高级键盘设置」打开页面，确认权限正常，拖动不应用、单击应用才保存。
3. 对支持背光的、已认证键盘分别验收关闭、中间亮度、满亮。从低环境光下观察键帽背光，
   不用 Num/Caps 灯或 HAL 写入返回值代替。确认不支持的型号不发亮度请求。
4. 保留中间值，验证翻折熄灯、展开恢复、摘装恢复、息屏后正常唤醒恢复，且键盘和触控板不回归。
5. 在原厂与候选上用已识别的键盘输入节点做一次有限时长的 Fn 调光试按，并同步观察实物灯光。
   原厂 `Generic.kl` 确有 Linux 228/229/230 的背光按键映射，但 Native05 的 Xiaomi Keyboard
   节点现有能力列表未声明 `KEY_KBDILLUM*`。这只是能力快照，不能替代实按；不要把屏幕亮度键重映射。
6. 原厂存在单独的 `0xf0` 命令状态回复，其中背光命令标识为 `0x23`；现有通用回复校验把该位置解释为
   正常数据长度，不能靠放宽现有校验直接把此回复作为成功。先抓取真实的有界亮度回复样本再加专用校验；
   不记录认证挑战、令牌或无关键盘输入。
